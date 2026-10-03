"""
GeoJSON 3D GIS Exporter for Smart Grid Digital Twin.
Produces GeoJSON FeatureCollections for 3D extruded buildings, electrical feeders,
distribution poles, transformer stations, and 3D drone flight paths.
Ready for Deck.gl, MapLibre, Mapbox GL JS, or Cesium.
"""
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from engine.digital_twin import SmartGridDigitalTwin


class GeoJSONTwinExporter:
    """Exports synchronized twin spatial state into standard GeoJSON 3D structures."""

    def __init__(self, twin: SmartGridDigitalTwin):
        self.twin = twin

    def _get_risk_color_rgba(self, risk_level: str, cause: str) -> List[int]:
        """Returns RGBA color array matching the futuristic cyber-physical aesthetic."""
        if risk_level == "CRITICAL" or cause == "THEFT_TAMPERING":
            return [255, 45, 85, 200]    # Glowing neon red / crimson
        elif risk_level == "HIGH" or cause == "METER_MALFUNCTION":
            return [255, 140, 0, 190]   # Glowing neon orange / amber
        elif risk_level == "MEDIUM" or cause == "COMM_FAILURE":
            return [240, 200, 30, 170]  # Amber / yellow
        elif cause == "LEGITIMATE_ABNORMAL":
            return [0, 210, 140, 180]   # Emerald / cyan surge indicator
        else:
            return [120, 150, 240, 95]  # Translucent lavender cyber glass

    def export_buildings_geojson(self) -> Dict[str, Any]:
        """Exports 3D building polygons with live anomaly risk colors and heights."""
        features = []
        for c_id, consumer in self.twin.topology.consumers.items():
            anomaly = self.twin.latest_anomaly_results.get(c_id)
            dual_rec = self.twin.latest_dual_records.get(c_id)

            risk_level = anomaly.risk_level if anomaly else "NORMAL"
            cause = anomaly.probable_cause if anomaly else "NORMAL"
            score = anomaly.anomaly_score if anomaly else 10.0
            fill_rgba = self._get_risk_color_rgba(risk_level, cause)

            rep_kw = dual_rec.reported.active_power_kw if dual_rec and dual_rec.reported else 0.0
            true_kw = dual_rec.ground_truth.active_power_kw if dual_rec else 0.0

            properties = {
                "id": consumer.id,
                "meter_id": consumer.meter_id,
                "name": consumer.name,
                "category": consumer.category,
                "contracted_load_kw": consumer.contracted_load_kw,
                "height": consumer.building_height_m,
                "elevation": consumer.coordinate.elevation_m,
                "zone_id": consumer.zone_id,
                "transformer_id": consumer.transformer_id,
                "feeder_id": consumer.feeder_id,
                "risk_level": risk_level,
                "probable_cause": cause,
                "anomaly_score": round(score, 1),
                "reported_kw": round(rep_kw, 3),
                "true_kw": round(true_kw, 3),
                "fill_color": fill_rgba,
                "wireframe_color": [255, 255, 255, 160],
                "is_anomalous": risk_level in ["MEDIUM", "HIGH", "CRITICAL"],
            }

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [consumer.building_polygon],
                },
                "properties": properties,
            })

        return {
            "type": "FeatureCollection",
            "name": "SmartGrid_3D_Buildings",
            "features": features,
        }

    def export_grid_lines_geojson(self) -> Dict[str, Any]:
        """Exports electrical distribution lines from substation -> transformers -> poles -> houses."""
        features = []
        top = self.twin.topology

        # 1. 11kV Feeder Trunks (Substation to Transformers)
        sub_c = top.substation_coord
        for tx_id, tx in top.transformers.items():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [sub_c.lon, sub_c.lat, sub_c.elevation_m],
                        [tx.coordinate.lon, tx.coordinate.lat, tx.coordinate.elevation_m],
                    ],
                },
                "properties": {
                    "type": "primary_feeder_11kv",
                    "id": f"LINE_{sub_c.lat}_{tx.id}",
                    "name": f"11kV Feeder to {tx.name}",
                    "color": [0, 220, 255, 220],
                    "width": 3.5,
                },
            })

        # 2. LV Main Lines (Transformers to Distribution Poles)
        for p_id, pole in top.poles.items():
            tx = top.transformers.get(pole.transformer_id)
            if tx:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [tx.coordinate.lon, tx.coordinate.lat, tx.coordinate.elevation_m],
                            [pole.coordinate.lon, pole.coordinate.lat, pole.coordinate.elevation_m],
                        ],
                    },
                    "properties": {
                        "type": "lv_main_dist_line",
                        "id": f"LINE_{tx.id}_{pole.id}",
                        "name": f"LV Trunk to {pole.id}",
                        "color": [0, 180, 230, 180],
                        "width": 2.2,
                    },
                })

        # 3. Service Drop Lines (Poles to Consumers)
        for c_id, consumer in top.consumers.items():
            # Find connecting pole
            assigned_pole = None
            for p in top.poles.values():
                if c_id in p.connected_consumer_ids:
                    assigned_pole = p
                    break

            if assigned_pole:
                c_coord = consumer.coordinate
                p_coord = assigned_pole.coordinate
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [p_coord.lon, p_coord.lat, p_coord.elevation_m],
                            [c_coord.lon, c_coord.lat, c_coord.elevation_m],
                        ],
                    },
                    "properties": {
                        "type": "service_drop",
                        "id": f"DROP_{consumer.id}",
                        "consumer_id": consumer.id,
                        "color": [255, 240, 160, 140],
                        "width": 1.2,
                    },
                })

        return {
            "type": "FeatureCollection",
            "name": "Electrical_Network_Topology",
            "features": features,
        }

    def export_transformers_geojson(self) -> Dict[str, Any]:
        """Exports distribution transformers and substation as spatial points."""
        features = []
        top = self.twin.topology

        # Substation
        sub_c = top.substation_coord
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [sub_c.lon, sub_c.lat, sub_c.elevation_m],
            },
            "properties": {
                "id": top.substation_id,
                "type": "primary_substation",
                "name": "Central 33/11kV Substation",
                "voltage": "33kV / 11kV",
                "icon": "substation",
                "color": [0, 255, 200, 255],
            },
        })

        # Transformers
        for tx_id, tx in top.transformers.items():
            tx_rep = self.twin.latest_transformer_reports.get(tx_id)
            ntl_pct = tx_rep.unexplained_loss_pct if tx_rep else 0.0
            status = tx_rep.status if tx_rep else "OPTIMAL"

            color = [0, 255, 180, 255]
            if "CRITICAL" in status or ntl_pct > 12.0:
                color = [255, 50, 50, 255]
            elif "SUSPICIOUS" in status or ntl_pct > 6.0:
                color = [255, 170, 0, 255]

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [tx.coordinate.lon, tx.coordinate.lat, tx.coordinate.elevation_m],
                },
                "properties": {
                    "id": tx.id,
                    "type": "distribution_transformer",
                    "name": tx.name,
                    "zone_id": tx.zone_id,
                    "capacity_kva": tx.capacity_kva,
                    "unexplained_loss_pct": round(ntl_pct, 1),
                    "status": status,
                    "connected_consumers": len(tx.connected_consumer_ids),
                    "color": color,
                },
            })

        return {
            "type": "FeatureCollection",
            "name": "Transformer_Stations",
            "features": features,
        }

    def export_drone_flight_geojson(self) -> Dict[str, Any]:
        """Exports 3D autonomous drone flight path and waypoints."""
        features = []
        flight = self.twin.latest_drone_flight
        if not flight or not flight.line_coordinates_3d:
            return {"type": "FeatureCollection", "features": []}

        # 3D Flight Line
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": flight.line_coordinates_3d,
            },
            "properties": {
                "type": "drone_flight_path_3d",
                "base_hub": flight.base_hub_id,
                "total_distance_m": flight.total_distance_m,
                "flight_minutes": flight.estimated_flight_minutes,
                "targets_count": flight.targets_inspected,
                "color": [255, 0, 180, 240], # Neon magenta flight corridor
                "width": 3.0,
            },
        })

        # Waypoints
        for idx, wp in enumerate(flight.waypoints):
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [wp.lon, wp.lat, wp.altitude_m],
                },
                "properties": {
                    "index": idx + 1,
                    "action": wp.action,
                    "target_id": wp.target_id,
                    "altitude_m": wp.altitude_m,
                },
            })

        return {
            "type": "FeatureCollection",
            "name": "Drone_Inspection_Mission",
            "features": features,
        }

    def export_all_to_files(self, output_dir: str):
        """Dumps all GeoJSON layers to disk."""
        import os
        os.makedirs(output_dir, exist_ok=True)

        with open(f"{output_dir}/buildings_3d.geojson", "w") as f:
            json.dump(self.export_buildings_geojson(), f, indent=2)

        with open(f"{output_dir}/grid_lines.geojson", "w") as f:
            json.dump(self.export_grid_lines_geojson(), f, indent=2)

        with open(f"{output_dir}/transformers.geojson", "w") as f:
            json.dump(self.export_transformers_geojson(), f, indent=2)

        with open(f"{output_dir}/drone_path.geojson", "w") as f:
            json.dump(self.export_drone_flight_geojson(), f, indent=2)
