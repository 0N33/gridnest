"""
Procedural 3D GIS City Cluster and Power Distribution Grid Generator.
Creates realistic 3D building polygons, distribution transformers, utility poles,
and service line geometries across two distinct transformer zones.
"""
from __future__ import annotations
import math
import random
from typing import List, Tuple, Dict, Any
from config import CONFIG
from models.topology import (
    Coordinate,
    ConsumerNode,
    TransformerNode,
    FeederNode,
    DistributionPole,
    GridTopology,
)


class CityGISGenerator:
    """Generates a complete 3D GIS city cluster with 2 transformer zones and distribution topology."""

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)
        self.base_lat = CONFIG.BASE_LATITUDE
        self.base_lon = CONFIG.BASE_LONGITUDE

    def _meters_to_lat_lon(self, dx_m: float, dy_m: float, base_lat: float, base_lon: float) -> Tuple[float, float]:
        """Convert local cartesian offset in meters (x=East, y=North) to WGS84 lat/lon."""
        r_earth = 6371000.0
        d_lat = (dy_m / r_earth) * (180.0 / math.pi)
        d_lon = (dx_m / (r_earth * math.cos(math.radians(base_lat)))) * (180.0 / math.pi)
        return base_lat + d_lat, base_lon + d_lon

    def _create_building_footprint(
        self, center_lat: float, center_lon: float, width_m: float, depth_m: float, rotation_deg: float = 0.0
    ) -> List[List[float]]:
        """Creates a closed GeoJSON polygon [[lon, lat], ...] for building extrusion."""
        angle = math.radians(rotation_deg)
        hw = width_m / 2.0
        hd = depth_m / 2.0

        # Local corners in meters
        corners = [
            (-hw, -hd),
            (hw, -hd),
            (hw, hd),
            (-hw, hd),
            (-hw, -hd), # Close loop
        ]

        coords = []
        for x, y in corners:
            # Rotate
            rx = x * math.cos(angle) - y * math.sin(angle)
            ry = x * math.sin(angle) + y * math.cos(angle)
            lat, lon = self._meters_to_lat_lon(rx, ry, center_lat, center_lon)
            coords.append([round(lon, 7), round(lat, 7)])

        return coords

    def build_grid(self) -> GridTopology:
        """Constructs the complete 2-zone smart grid digital twin topology."""
        topology = GridTopology()

        # 1. Primary Feeders (Feeder F1 - North Zone, Feeder F2 - South Zone)
        f1_lat, f1_lon = self._meters_to_lat_lon(0, 150, self.base_lat, self.base_lon)
        f2_lat, f2_lon = self._meters_to_lat_lon(0, -150, self.base_lat, self.base_lon)

        feeder_1 = FeederNode(
            id="FDR_NORTH_11KV",
            name="Feeder 1 - North 11kV Trunk",
            substation_id=topology.substation_id,
            coordinate=Coordinate(lat=f1_lat, lon=f1_lon, elevation_m=216.0),
        )
        feeder_2 = FeederNode(
            id="FDR_SOUTH_11KV",
            name="Feeder 2 - South 11kV Trunk",
            substation_id=topology.substation_id,
            coordinate=Coordinate(lat=f2_lat, lon=f2_lon, elevation_m=214.0),
        )
        topology.add_feeder(feeder_1)
        topology.add_feeder(feeder_2)

        # 2. Distribution Transformers (Zone 1: TX-101 North, Zone 2: TX-102 South)
        tx1_lat, tx1_lon = self._meters_to_lat_lon(20, 220, self.base_lat, self.base_lon)
        tx2_lat, tx2_lon = self._meters_to_lat_lon(-20, -220, self.base_lat, self.base_lon)

        tx1 = TransformerNode(
            id="TX_101",
            name="Distribution Transformer TX-101 (North Sector)",
            zone_id="Zone_1_North",
            coordinate=Coordinate(lat=tx1_lat, lon=tx1_lon, elevation_m=218.0),
            capacity_kva=CONFIG.TRANSFORMER_CAPACITY_KVA,
            feeder_id="FDR_NORTH_11KV",
        )
        tx2 = TransformerNode(
            id="TX_102",
            name="Distribution Transformer TX-102 (South Sector)",
            zone_id="Zone_2_South",
            coordinate=Coordinate(lat=tx2_lat, lon=tx2_lon, elevation_m=216.0),
            capacity_kva=CONFIG.TRANSFORMER_CAPACITY_KVA,
            feeder_id="FDR_SOUTH_11KV",
        )
        topology.add_transformer(tx1)
        topology.add_transformer(tx2)

        # 3. Create Poles and Buildings for each zone
        self._populate_zone(
            topology=topology,
            transformer=tx1,
            zone_id="Zone_1_North",
            feeder_id="FDR_NORTH_11KV",
            center_dx=0.0,
            center_dy=220.0,
            prefix="N",
        )
        self._populate_zone(
            topology=topology,
            transformer=tx2,
            zone_id="Zone_2_South",
            feeder_id="FDR_SOUTH_11KV",
            center_dx=0.0,
            center_dy=-220.0,
            prefix="S",
        )

        return topology

    def _populate_zone(
        self,
        topology: GridTopology,
        transformer: TransformerNode,
        zone_id: str,
        feeder_id: str,
        center_dx: float,
        center_dy: float,
        prefix: str,
    ):
        """Populates utility poles, street avenues, and 24 buildings per zone."""
        houses_count = CONFIG.HOUSES_PER_TRANSFORMER # 24 houses per zone
        poles_count = 6  # 4 houses per pole

        # Create 6 distribution poles arranged along two parallel avenues
        pole_objs = []
        for p_idx in range(poles_count):
            row = p_idx // 3
            col = p_idx % 3
            # Street grid layout in meters relative to zone center
            p_dx = center_dx + (col - 1) * 80.0
            p_dy = center_dy + (row * 60.0 - 30.0)

            plat, plon = self._meters_to_lat_lon(p_dx, p_dy, self.base_lat, self.base_lon)
            pole = DistributionPole(
                id=f"POLE_{prefix}_{p_idx+1:02d}",
                coordinate=Coordinate(lat=plat, lon=plon, elevation_m=218.0),
                feeder_id=feeder_id,
                transformer_id=transformer.id,
            )
            topology.add_pole(pole)
            pole_objs.append(pole)

        # Create houses around each pole
        categories = ["Residential"] * 18 + ["Commercial"] * 5 + ["LightIndustrial"] * 1
        self.random.shuffle(categories)

        phases = ["R", "Y", "B"]

        for h_idx in range(houses_count):
            pole_idx = h_idx // 4
            assigned_pole = pole_objs[pole_idx]
            sub_idx = h_idx % 4

            # Offset building from its pole (North-East, North-West, South-East, South-West)
            offsets = [
                (-22.0, -20.0),
                (22.0, -20.0),
                (-22.0, 20.0),
                (22.0, 20.0),
            ]
            ox, oy = offsets[sub_idx]
            # Add subtle jitter for realistic architectural look
            ox += self.random.uniform(-3.0, 3.0)
            oy += self.random.uniform(-3.0, 3.0)

            # Building center in lat/lon
            p_coord = assigned_pole.coordinate
            # Compute meter offset from base
            b_lat, b_lon = self._meters_to_lat_lon(ox, oy, p_coord.lat, p_coord.lon)

            # Category & contract load
            cat = categories[h_idx]
            if cat == "Residential":
                contracted_kw = round(self.random.choice([3.0, 4.5, 6.0]), 1)
                levels = self.random.choice([1, 2, 3])
                width_m = self.random.uniform(10.0, 14.0)
                depth_m = self.random.uniform(12.0, 16.0)
            elif cat == "Commercial":
                contracted_kw = round(self.random.choice([8.0, 12.0, 15.0]), 1)
                levels = self.random.choice([2, 3, 4])
                width_m = self.random.uniform(14.0, 20.0)
                depth_m = self.random.uniform(16.0, 22.0)
            else: # LightIndustrial
                contracted_kw = 25.0
                levels = self.random.choice([1, 2])
                width_m = 24.0
                depth_m = 28.0

            height_m = levels * 3.2 # 3.2m per floor

            footprint = self._create_building_footprint(
                center_lat=b_lat,
                center_lon=b_lon,
                width_m=width_m,
                depth_m=depth_m,
                rotation_deg=self.random.choice([0, 15, -15, 30]),
            )

            # Service line distance from pole to house entrance
            drop_dist_m = math.sqrt(ox**2 + oy**2)
            # Distance from pole to transformer
            pole_to_tx_dist = assigned_pole.coordinate.distance_to(transformer.coordinate)
            total_cable_dist = round(pole_to_tx_dist + drop_dist_m, 1)

            consumer_id = f"CONS_{prefix}_{h_idx+1:03d}"
            meter_id = f"MTR_{prefix}_{h_idx+1:03d}"

            consumer = ConsumerNode(
                id=consumer_id,
                meter_id=meter_id,
                name=f"{cat} Consumer #{h_idx+1} ({zone_id})",
                category=cat,
                contracted_load_kw=contracted_kw,
                coordinate=Coordinate(lat=b_lat, lon=b_lon, elevation_m=218.0 + height_m),
                building_polygon=footprint,
                building_height_m=round(height_m, 1),
                zone_id=zone_id,
                transformer_id=transformer.id,
                feeder_id=feeder_id,
                line_distance_m=total_cable_dist,
                phase=phases[h_idx % 3],
            )

            topology.add_consumer(consumer, pole_id=assigned_pole.id)
