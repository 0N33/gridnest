"""
GeoJSON 3D GIS Exporter for 3-Zone Smart Grid Digital Twin.
Produces GeoJSON FeatureCollections for:
- 3D Extruded Buildings & Power Station Facility
- Electrical Feeders, Transmission Corridors & Service Drops
- City Roads & Street Network (for realistic map appearance)
- Distribution Poles, Transmission Pylons, and Transformers
- 3D Autonomous Drone Flight Paths
"""
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from engine.digital_twin import SmartGridDigitalTwin
from models.topology import Coordinate


class GeoJSONTwinExporter:
    """Exports synchronized twin spatial state into standard GeoJSON 3D structures."""

    def __init__(self, twin: SmartGridDigitalTwin):
        self.twin = twin

    def _get_risk_color_rgba(self, risk_level: str, cause: str) -> List[int]:
        """Returns RGBA color array matching the architectural light/dark aesthetic."""
        if risk_level == "CRITICAL" or cause == "THEFT_TAMPERING":
            return [239, 68, 68, 220]    # Coral Red
        elif risk_level == "HIGH" or cause == "METER_MALFUNCTION":
            return [249, 115, 22, 220]   # Safety Orange
        elif risk_level == "MEDIUM" or cause == "COMM_FAILURE":
            return [234, 179, 8, 210]    # Amber
        elif cause == "LEGITIMATE_ABNORMAL":
            return [16, 185, 129, 220]   # Emerald Surge
        else:
            return [255, 255, 255, 210]  # Clean Porcelain White

    def export_buildings_geojson(self) -> Dict[str, Any]:
        """Exports 3D building polygons including the Power Station and both city sectors."""
        features = []
        top = self.twin.topology

        # 1. Power Station Facility (Zone 0)
        if top.power_station and top.power_station.footprint_polygon:
            ps = top.power_station
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ps.footprint_polygon],
                },
                "properties": {
                    "id": ps.id,
                    "meter_id": "STATION_BULK_MTR_01",
                    "name": ps.name,
                    "category": "PowerGenerationSubstation",
                    "contracted_load_kw": 5000.0,
                    "height": ps.building_height_m,
                    "elevation": ps.coordinate.elevation_m,
                    "zone_id": ps.zone_id,
                    "transformer_id": "PRIMARY_33KV_STATION",
                    "feeder_id": "GRID_INTERCONNECT",
                    "risk_level": "NORMAL",
                    "probable_cause": "NORMAL",
                    "anomaly_score": 0.0,
                    "reported_kw": ps.iot_sensors.get("total_generation_kw", 450.0),
                    "true_kw": ps.iot_sensors.get("total_generation_kw", 450.0),
                    "fill_color": [37, 99, 235, 220], # Blue Power Station
                    "wireframe_color": [29, 78, 216, 255],
                    "is_power_station": True,
                    "is_anomalous": False,
                },
            })

        # 2. City Sector Buildings (Zone 1 & Zone 2)
        for c_id, consumer in top.consumers.items():
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
                "wireframe_color": [148, 163, 184, 200],
                "is_power_station": False,
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
            "name": "SmartGrid_3D_Buildings_3Zones",
            "features": features,
        }

    def export_roads_geojson(self) -> Dict[str, Any]:
        """Exports city street grid network geometries."""
        features = []
        for r_id, road in self.twin.topology.roads.items():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": road.coordinates,
                },
                "properties": road.to_dict(),
            })
        return {
            "type": "FeatureCollection",
            "name": "City_Road_Network",
            "features": features,
        }

    def export_grid_lines_geojson(self) -> Dict[str, Any]:
        """Exports electrical lines: 33/11kV trunks -> distribution mains -> service drops."""
        features = []
        top = self.twin.topology

        # 1. Transmission Feeder Trunks (Power Station -> Pylons -> Transformers)
        ps_coord = top.power_station.coordinate if top.power_station else Coordinate(lat=28.6139, lon=77.2090)

        for tx_id, tx in top.transformers.items():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ps_coord.lon, ps_coord.lat, ps_coord.elevation_m + 8.0],
                        [tx.coordinate.lon, tx.coordinate.lat, tx.coordinate.elevation_m + 5.0],
                    ],
                },
                "properties": {
                    "type": "transmission_feeder_11kv",
                    "id": f"TRUNK_{tx.id}",
                    "name": f"11kV Feeder to {tx.name}",
                    "color": [29, 78, 216, 255], # Deep Royal Blue
                    "width": 4.0,
                },
            })

        # 2. LV Main Street Distribution Lines (Pole to Pole along streets)
        def add_line(coord1: Coordinate, coord2: Coordinate, line_id: str, line_name: str):
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [coord1.lon, coord1.lat, coord1.elevation_m + 4.5],
                        [coord2.lon, coord2.lat, coord2.elevation_m + 4.5],
                    ],
                },
                "properties": {
                    "type": "lv_street_dist_line",
                    "id": line_id,
                    "name": line_name,
                    "color": [71, 85, 105, 240], # Slate Grey Overhead Wire
                    "width": 2.5,
                },
            })

        for prefix, tx_id in [("N", "TX_101"), ("S", "TX_102")]:
            tx = top.transformers.get(tx_id)
            p1 = top.poles.get(f"POLE_{prefix}_01")
            if tx and p1:
                add_line(tx.coordinate, p1.coordinate, f"FEED_{tx_id}_TO_POLE01", f"Feeder Drop to Pole 1 ({prefix})")

            # Street 1 corridor: Pole 1 -> 2 -> 3 -> 4 -> 5 -> 6
            for i in range(1, 6):
                pa = top.poles.get(f"POLE_{prefix}_{i:02d}")
                pb = top.poles.get(f"POLE_{prefix}_{i+1:02d}")
                if pa and pb:
                    add_line(pa.coordinate, pb.coordinate, f"ST1_{prefix}_{i}_{i+1}", f"Street 1 Overhead Main {prefix}")

            # Avenue connection: Pole 2 -> Pole 8 (along Avenue A at x=70)
            p2 = top.poles.get(f"POLE_{prefix}_02")
            p8 = top.poles.get(f"POLE_{prefix}_08")
            if p2 and p8:
                add_line(p2.coordinate, p8.coordinate, f"AVE1_{prefix}_2_8", f"Avenue A Tie Line {prefix}")

            # Street 2 corridor: Pole 7 -> 8 -> 9 -> 10 -> 11 -> 12
            for i in range(7, 12):
                pa = top.poles.get(f"POLE_{prefix}_{i:02d}")
                pb = top.poles.get(f"POLE_{prefix}_{i+1:02d}")
                if pa and pb:
                    add_line(pa.coordinate, pb.coordinate, f"ST2_{prefix}_{i}_{i+1}", f"Street 2 Overhead Main {prefix}")

            # Cross-tie: Pole 5 -> 11 (along Avenue B at x=175)
            p5 = top.poles.get(f"POLE_{prefix}_05")
            p11 = top.poles.get(f"POLE_{prefix}_11")
            if p5 and p11:
                add_line(p5.coordinate, p11.coordinate, f"AVE2_{prefix}_5_11", f"Avenue B Tie Line {prefix}")

        # 3. Service Drop Lines (Poles directly to Consumer Rooftops)
        for c_id, consumer in top.consumers.items():
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
                            [p_coord.lon, p_coord.lat, p_coord.elevation_m + 4.0],
                            [c_coord.lon, c_coord.lat, c_coord.elevation_m],
                        ],
                    },
                    "properties": {
                        "type": "service_drop",
                        "id": f"DROP_{consumer.id}",
                        "consumer_id": consumer.id,
                        "color": [180, 83, 9, 220], # Warm Amber
                        "width": 1.5,
                    },
                })

        return {
            "type": "FeatureCollection",
            "name": "Electrical_Network_Wiring",
            "features": features,
        }

    def export_transformers_geojson(self) -> Dict[str, Any]:
        """Exports power station hub and distribution transformers."""
        features = []
        top = self.twin.topology

        # Power Station Hub (Zone 0)
        if top.power_station:
            ps = top.power_station
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [ps.coordinate.lon, ps.coordinate.lat, ps.coordinate.elevation_m],
                },
                "properties": {
                    "id": ps.id,
                    "type": "power_station_hub",
                    "name": ps.name,
                    "zone_id": ps.zone_id,
                    "capacity_mva": ps.capacity_mva,
                    "iot_sensors": ps.iot_sensors,
                    "color": [37, 99, 235, 255],
                },
            })

        # Distribution Transformers (Zone 1 & 2)
        for tx_id, tx in top.transformers.items():
            tx_rep = self.twin.latest_transformer_reports.get(tx_id)
            ntl_pct = tx_rep.unexplained_loss_pct if tx_rep else 0.0
            status = tx_rep.status if tx_rep else "OPTIMAL"

            color = [2, 132, 199, 255]
            if "CRITICAL" in status or ntl_pct > 10.0:
                color = [239, 68, 68, 255]
            elif "SUSPICIOUS" in status or ntl_pct > 5.0:
                color = [249, 115, 22, 255]

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
            "name": "Transformer_Stations_3Zones",
            "features": features,
        }

    def export_drone_flight_geojson(self) -> Dict[str, Any]:
        """Exports 3D autonomous drone flight path."""
        features = []
        flight = self.twin.latest_drone_flight
        if not flight or not flight.line_coordinates_3d:
            return {"type": "FeatureCollection", "features": []}

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
                "color": [217, 70, 239, 240], # Magenta
                "width": 3.0,
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

        with open(f"{output_dir}/roads.geojson", "w") as f:
            json.dump(self.export_roads_geojson(), f, indent=2)

        with open(f"{output_dir}/grid_lines.geojson", "w") as f:
            json.dump(self.export_grid_lines_geojson(), f, indent=2)

        with open(f"{output_dir}/transformers.geojson", "w") as f:
            json.dump(self.export_transformers_geojson(), f, indent=2)

        with open(f"{output_dir}/drone_path.geojson", "w") as f:
            json.dump(self.export_drone_flight_geojson(), f, indent=2)
