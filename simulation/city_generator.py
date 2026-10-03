"""
Procedural 3D GIS Generator for 3-Zone Smart Grid.
Zone 0: Central Power Generation Station & 33kV Substation Hub
Zone 1: West City District (Commercial / Urban Sector - TX-101)
Zone 2: East City District (Residential / Suburban Sector - TX-102)

Generates an authentic urban street grid with paved avenues, dedicated city blocks,
buildings situated strictly inside blocks with clean setbacks, overhead electric lines
running pole-to-pole along curbs, and short service drops connecting directly into
rooftop weatherhead boxes. Zero road or building overlaps.
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
    PowerStationNode,
    TransmissionPylon,
    RoadSegment,
    GridTopology,
)


class CityGISGenerator:
    """Generates the 3-Zone cyber-physical power system and structured urban spatial grid."""

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

        corners = [
            (-hw, -hd),
            (hw, -hd),
            (hw, hd),
            (-hw, hd),
            (-hw, -hd),
        ]

        coords = []
        for x, y in corners:
            rx = x * math.cos(angle) - y * math.sin(angle)
            ry = x * math.sin(angle) + y * math.cos(angle)
            lat, lon = self._meters_to_lat_lon(rx, ry, center_lat, center_lon)
            coords.append([round(lon, 7), round(lat, 7)])

        return coords

    def build_grid(self) -> GridTopology:
        """Constructs the complete 3-zone smart grid digital twin."""
        topology = GridTopology()

        # =========================================================================
        # 1. ZONE 0: CENTRAL POWER STATION & 33kV PRIMARY SUBSTATION (South Gateway)
        # =========================================================================
        ps_dx = 0.0
        ps_dy = -220.0
        ps_lat, ps_lon = self._meters_to_lat_lon(ps_dx, ps_dy, self.base_lat, self.base_lon)

        ps_footprint = self._create_building_footprint(
            center_lat=ps_lat,
            center_lon=ps_lon,
            width_m=48.0,
            depth_m=32.0,
            rotation_deg=0.0,
        )

        power_station = PowerStationNode(
            id="PS_CENTRAL_01",
            name=CONFIG.POWER_STATION_NAME,
            zone_id=CONFIG.ZONE_POWER_STATION,
            coordinate=Coordinate(lat=ps_lat, lon=ps_lon, elevation_m=220.0),
            capacity_mva=CONFIG.POWER_STATION_CAPACITY_MVA,
            transmission_voltage_kv=CONFIG.TRANSMISSION_VOLTAGE_KV,
            primary_feeder_voltage_kv=CONFIG.PRIMARY_FEEDER_VOLTAGE_KV,
            footprint_polygon=ps_footprint,
            building_height_m=16.0,
            feeder_ids=["FDR_NORTH_11KV", "FDR_SOUTH_11KV"],
            iot_sensors={
                "gateway_id": "IOT_GATEWAY_PS_01",
                "bus_voltage_kv": 33.15,
                "grid_frequency_hz": 50.02,
                "transformer_oil_temp_c": 63.4,
                "ambient_temp_c": 31.5,
                "power_factor": 0.98,
                "total_generation_kw": 485.2,
                "reactive_power_kvar": 98.4,
                "switchgear_status": "CLOSED_HEALTHY",
                "cooling_fan_status": "ACTIVE_STAGE_1",
                "feeder_1_kw": 245.8,
                "feeder_2_kw": 239.4,
            },
        )
        topology.set_power_station(power_station)

        # Transmission Pylons along high-voltage corridors to the 2 district substations
        p_n1_lat, p_n1_lon = self._meters_to_lat_lon(-65.0, -140.0, self.base_lat, self.base_lon)
        p_n2_lat, p_n2_lon = self._meters_to_lat_lon(-115.0, -85.0, self.base_lat, self.base_lon)
        p_s1_lat, p_s1_lon = self._meters_to_lat_lon(65.0, -140.0, self.base_lat, self.base_lon)
        p_s2_lat, p_s2_lon = self._meters_to_lat_lon(115.0, -85.0, self.base_lat, self.base_lon)

        topology.add_pylon(TransmissionPylon(id="PYLON_N_01", coordinate=Coordinate(lat=p_n1_lat, lon=p_n1_lon, elevation_m=220.0), feeder_id="FDR_NORTH_11KV"))
        topology.add_pylon(TransmissionPylon(id="PYLON_N_02", coordinate=Coordinate(lat=p_n2_lat, lon=p_n2_lon, elevation_m=220.0), feeder_id="FDR_NORTH_11KV"))
        topology.add_pylon(TransmissionPylon(id="PYLON_S_01", coordinate=Coordinate(lat=p_s1_lat, lon=p_s1_lon, elevation_m=220.0), feeder_id="FDR_SOUTH_11KV"))
        topology.add_pylon(TransmissionPylon(id="PYLON_S_02", coordinate=Coordinate(lat=p_s2_lat, lon=p_s2_lon, elevation_m=220.0), feeder_id="FDR_SOUTH_11KV"))

        # =========================================================================
        # 2. CITY STREET & ROAD NETWORK
        # =========================================================================
        self._generate_road_network(topology)

        # =========================================================================
        # 3. DISTRIBUTION TRANSFORMERS (Zone 1 West TX-101 & Zone 2 East TX-102)
        # =========================================================================
        tx1_dx, tx1_dy = -140.0, -50.0
        tx2_dx, tx2_dy = 140.0, -50.0

        tx1_lat, tx1_lon = self._meters_to_lat_lon(tx1_dx, tx1_dy, self.base_lat, self.base_lon)
        tx2_lat, tx2_lon = self._meters_to_lat_lon(tx2_dx, tx2_dy, self.base_lat, self.base_lon)

        feeder_1 = FeederNode(
            id="FDR_NORTH_11KV",
            name="11kV Feeder Trunk 1 (Zone 1 West District)",
            substation_id=power_station.id,
            coordinate=Coordinate(lat=tx1_lat, lon=tx1_lon, elevation_m=218.0),
        )
        feeder_2 = FeederNode(
            id="FDR_SOUTH_11KV",
            name="11kV Feeder Trunk 2 (Zone 2 East District)",
            substation_id=power_station.id,
            coordinate=Coordinate(lat=tx2_lat, lon=tx2_lon, elevation_m=216.0),
        )
        topology.add_feeder(feeder_1)
        topology.add_feeder(feeder_2)

        tx1 = TransformerNode(
            id="TX_101",
            name="Distribution Transformer TX-101 (Zone 1 Commercial)",
            zone_id=CONFIG.ZONE_CITY_NORTH,
            coordinate=Coordinate(lat=tx1_lat, lon=tx1_lon, elevation_m=218.0),
            capacity_kva=CONFIG.TRANSFORMER_CAPACITY_KVA,
            feeder_id="FDR_NORTH_11KV",
            iot_sensors={
                "gateway_id": "IOT_GW_TX_101",
                "primary_voltage_kv": 11.05,
                "secondary_voltage_v": 416.2,
                "oil_temperature_c": 61.2,
                "ambient_temp_c": 32.4,
                "phase_unbalance_pct": 3.8,
                "thd_voltage_pct": 2.1,
                "status": "ALERT_DISCREPANCY",
                "protocol": "MQTT / IEC 61850",
            },
        )
        tx2 = TransformerNode(
            id="TX_102",
            name="Distribution Transformer TX-102 (Zone 2 Residential)",
            zone_id=CONFIG.ZONE_CITY_SOUTH,
            coordinate=Coordinate(lat=tx2_lat, lon=tx2_lon, elevation_m=216.0),
            capacity_kva=CONFIG.TRANSFORMER_CAPACITY_KVA,
            feeder_id="FDR_SOUTH_11KV",
            iot_sensors={
                "gateway_id": "IOT_GW_TX_102",
                "primary_voltage_kv": 11.02,
                "secondary_voltage_v": 415.8,
                "oil_temperature_c": 56.4,
                "ambient_temp_c": 32.1,
                "phase_unbalance_pct": 1.9,
                "thd_voltage_pct": 1.8,
                "status": "ONLINE_HEALTHY",
                "protocol": "MQTT / IEC 61850",
            },
        )
        topology.add_transformer(tx1)
        topology.add_transformer(tx2)

        # =========================================================================
        # 4. STRUCTURED CITY DISTRICTS (Zero-overlap City Blocks & Curbside Poles)
        # =========================================================================
        # Zone 1: West District (Commercial / Urban)
        self._populate_district(
            topology=topology,
            transformer=tx1,
            zone_id=CONFIG.ZONE_CITY_NORTH,
            feeder_id="FDR_NORTH_11KV",
            x_sign=-1.0,  # Negative DX (West)
            prefix="N",
            category_bias="commercial",
        )

        # Zone 2: East District (Residential / Suburban)
        self._populate_district(
            topology=topology,
            transformer=tx2,
            zone_id=CONFIG.ZONE_CITY_SOUTH,
            feeder_id="FDR_SOUTH_11KV",
            x_sign=1.0,   # Positive DX (East)
            prefix="S",
            category_bias="residential",
        )

        return topology

    def _generate_road_network(self, topology: GridTopology):
        """Constructs an authentic urban road grid connecting the power station and 2 districts."""
        # 1. Central Energy Highway (Power Station dy=-220 to Main Cross Avenue dy=-60 along dx=0)
        p_hw_start = self._meters_to_lat_lon(0.0, -220.0, self.base_lat, self.base_lon)
        p_hw_end = self._meters_to_lat_lon(0.0, -60.0, self.base_lat, self.base_lon)
        topology.add_road(RoadSegment(
            id="ROAD_CENTRAL_HIGHWAY",
            name="Central Energy Highway",
            coordinates=[[p_hw_start[1], p_hw_start[0]], [p_hw_end[1], p_hw_end[0]]],
            width_m=14.0,
            road_type="highway",
        ))

        # 2. Main Metropolitan Cross Avenue (Runs along dy=-60 from dx=-230 to dx=230)
        p_cross_w = self._meters_to_lat_lon(-230.0, -60.0, self.base_lat, self.base_lon)
        p_cross_e = self._meters_to_lat_lon(230.0, -60.0, self.base_lat, self.base_lon)
        topology.add_road(RoadSegment(
            id="ROAD_MAIN_CROSS_AVENUE",
            name="Metropolitan Connecting Avenue",
            coordinates=[[p_cross_w[1], p_cross_w[0]], [p_cross_e[1], p_cross_e[0]]],
            width_m=14.0,
            road_type="avenue",
        ))

        # 3. Zone 1 (West District) Roads:
        # Avenues (North-South): dx = -180 and dx = -100, running dy=-60 to dy=160
        for idx, x_pos in enumerate([-180.0, -100.0]):
            ave_s = self._meters_to_lat_lon(x_pos, -60.0, self.base_lat, self.base_lon)
            ave_n = self._meters_to_lat_lon(x_pos, 160.0, self.base_lat, self.base_lon)
            topology.add_road(RoadSegment(
                id=f"ROAD_WEST_AVE_{idx+1}",
                name=f"West District Avenue #{idx+1}",
                coordinates=[[ave_s[1], ave_s[0]], [ave_n[1], ave_n[0]]],
                width_m=10.0,
                road_type="avenue",
            ))

        # Cross Streets (East-West): dy = 20 and dy = 110, running dx=-220 to dx=-60
        for idx, y_pos in enumerate([20.0, 110.0]):
            st_w = self._meters_to_lat_lon(-220.0, y_pos, self.base_lat, self.base_lon)
            st_e = self._meters_to_lat_lon(-60.0, y_pos, self.base_lat, self.base_lon)
            topology.add_road(RoadSegment(
                id=f"ROAD_WEST_ST_{idx+1}",
                name=f"West District Street #{idx+1}",
                coordinates=[[st_w[1], st_w[0]], [st_e[1], st_e[0]]],
                width_m=10.0,
                road_type="residential",
            ))

        # 4. Zone 2 (East District) Roads:
        # Avenues (North-South): dx = 100 and dx = 180, running dy=-60 to dy=160
        for idx, x_pos in enumerate([100.0, 180.0]):
            ave_s = self._meters_to_lat_lon(x_pos, -60.0, self.base_lat, self.base_lon)
            ave_n = self._meters_to_lat_lon(x_pos, 160.0, self.base_lat, self.base_lon)
            topology.add_road(RoadSegment(
                id=f"ROAD_EAST_AVE_{idx+1}",
                name=f"East District Avenue #{idx+1}",
                coordinates=[[ave_s[1], ave_s[0]], [ave_n[1], ave_n[0]]],
                width_m=10.0,
                road_type="avenue",
            ))

        # Cross Streets (East-West): dy = 20 and dy = 110, running dx=60 to dx=220
        for idx, y_pos in enumerate([20.0, 110.0]):
            st_w = self._meters_to_lat_lon(60.0, y_pos, self.base_lat, self.base_lon)
            st_e = self._meters_to_lat_lon(220.0, y_pos, self.base_lat, self.base_lon)
            topology.add_road(RoadSegment(
                id=f"ROAD_EAST_ST_{idx+1}",
                name=f"East District Street #{idx+1}",
                coordinates=[[st_w[1], st_w[0]], [st_e[1], st_e[0]]],
                width_m=10.0,
                road_type="residential",
            ))

    def _populate_district(
        self,
        topology: GridTopology,
        transformer: TransformerNode,
        zone_id: str,
        feeder_id: str,
        x_sign: float,
        prefix: str,
        category_bias: str,
    ):
        """
        Populates exactly 24 buildings strictly inside designated city blocks:
        - 12 curbside utility poles (6 on Street 2, 6 on Street 1).
        - 24 buildings placed neatly in 4 rows of 6 along street block frontages.
        - Exactly 2 buildings per pole with short perpendicular service drops.
        - Zero overlapping roads, zero overlapping sidewalks, zero overlapping buildings.
        """
        # Street centerlines: Street 2 (North) at dy = 110.0, Street 1 (South) at dy = 20.0
        # Poles placed along curbs (dy = 116.0 for Street 2, dy = 26.0 for Street 1)
        curb_st2_y = 116.0
        curb_st1_y = 26.0

        # 6 X-stations per district (spaced with generous buffers from avenues at |dx|=100 and |dx|=180)
        base_x_stations = [65.0, 82.0, 120.0, 140.0, 160.0, 205.0]
        x_stations = [x * x_sign for x in base_x_stations]
        if x_sign < 0:
            x_stations.sort()  # Keep left-to-right order for West district: -205 to -65

        pole_objs: List[DistributionPole] = []

        # Poles 1..6 along Street 2 curb (North Cross Street)
        for idx, px in enumerate(x_stations):
            plat, plon = self._meters_to_lat_lon(px, curb_st2_y, self.base_lat, self.base_lon)
            pole = DistributionPole(
                id=f"POLE_{prefix}_{idx+1:02d}",
                coordinate=Coordinate(lat=plat, lon=plon, elevation_m=218.0),
                feeder_id=feeder_id,
                transformer_id=transformer.id,
            )
            topology.add_pole(pole)
            pole_objs.append(pole)

        # Poles 7..12 along Street 1 curb (South Cross Street)
        for idx, px in enumerate(x_stations):
            plat, plon = self._meters_to_lat_lon(px, curb_st1_y, self.base_lat, self.base_lon)
            pole = DistributionPole(
                id=f"POLE_{prefix}_{idx+7:02d}",
                coordinate=Coordinate(lat=plat, lon=plon, elevation_m=218.0),
                feeder_id=feeder_id,
                transformer_id=transformer.id,
            )
            topology.add_pole(pole)
            pole_objs.append(pole)

        # Categories mix
        if category_bias == "commercial":
            categories = ["Commercial"] * 10 + ["Residential"] * 12 + ["LightIndustrial"] * 2
        else:
            categories = ["Residential"] * 20 + ["Commercial"] * 4

        self.random.shuffle(categories)
        phases = ["R", "Y", "B"]

        # 24 Buildings: exactly 2 buildings per pole (one North lot, one South lot)
        # Lot frontages in Y:
        # Street 2 (center 110): North lot at dy = 135 (+25m), South lot at dy = 85 (-25m)
        # Street 1 (center 20):  North lot at dy = 45 (+25m),  South lot at dy = -5 (-25m)
        for p_idx, pole in enumerate(pole_objs):
            is_st2 = p_idx < 6
            px = x_stations[p_idx % 6]

            if is_st2:
                lots_y = [135.0, 85.0]  # North lot, South lot
                curb_y = curb_st2_y
            else:
                lots_y = [45.0, -5.0]   # North lot, South lot
                curb_y = curb_st1_y

            for b_slot in range(2):
                h_idx = p_idx * 2 + b_slot
                by = lots_y[b_slot]
                bx = px

                b_lat, b_lon = self._meters_to_lat_lon(bx, by, self.base_lat, self.base_lon)

                cat = categories[h_idx]
                if cat == "Residential":
                    contracted_kw = round(self.random.choice([3.0, 4.5, 6.0]), 1)
                    levels = self.random.choice([1, 2, 3])
                    width_m = 12.0
                    depth_m = 12.0
                elif cat == "Commercial":
                    contracted_kw = round(self.random.choice([8.0, 12.0, 15.0]), 1)
                    levels = self.random.choice([3, 4, 5])
                    width_m = 14.0
                    depth_m = 14.0
                else:  # LightIndustrial
                    contracted_kw = 25.0
                    levels = 2
                    width_m = 16.0
                    depth_m = 16.0

                height_m = levels * 3.5

                footprint = self._create_building_footprint(
                    center_lat=b_lat,
                    center_lon=b_lon,
                    width_m=width_m,
                    depth_m=depth_m,
                    rotation_deg=0.0,
                )

                drop_dist_m = abs(by - curb_y)
                total_cable_dist = round(30.0 + (p_idx % 6) * 20.0 + drop_dist_m, 1)

                consumer_id = f"CONS_{prefix}_{h_idx+1:03d}"
                meter_id = f"MTR_{prefix}_{h_idx+1:03d}"

                consumer = ConsumerNode(
                    id=consumer_id,
                    meter_id=meter_id,
                    name=f"{cat} #{h_idx+1} ({zone_id.replace('Zone_', 'Z')})",
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
                    connected_pole_id=pole.id,
                )

                topology.add_consumer(consumer, pole_id=pole.id)
