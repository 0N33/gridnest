"""
Inspection Prioritizer and Autonomous Drone Flight Path Planner.
Ranks suspicious consumers by severity and financial loss impact,
and calculates 3D inspection trajectories for autonomous aerial/field inspection.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
from models.topology import Coordinate, ConsumerNode, TransformerNode
from engine.anomaly_detector import AnomalyDetectionResult


@dataclass
class InspectionTarget:
    consumer_id: str
    meter_id: str
    consumer_name: str
    coordinate: Coordinate
    building_height_m: float
    anomaly_score: float
    probable_cause: str
    risk_level: str
    priority_score: float
    rank: int
    unreported_loss_kw: float
    recommended_action: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "consumer_id": self.consumer_id,
            "meter_id": self.meter_id,
            "consumer_name": self.consumer_name,
            "coordinate": self.coordinate.to_dict(),
            "building_height_m": self.building_height_m,
            "anomaly_score": round(self.anomaly_score, 1),
            "probable_cause": self.probable_cause,
            "risk_level": self.risk_level,
            "priority_score": round(self.priority_score, 2),
            "unreported_loss_kw": round(self.unreported_loss_kw, 2),
            "recommended_action": self.recommended_action,
        }


@dataclass
class DroneWaypoint:
    lat: float
    lon: float
    altitude_m: float
    action: str              # "TAKEOFF", "CRUISE", "HOVER_INSPECT", "RETURN", "LAND"
    target_id: Optional[str] = None
    hover_duration_sec: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "altitude_m": self.altitude_m,
            "action": self.action,
            "target_id": self.target_id,
            "hover_duration_sec": self.hover_duration_sec,
        }


@dataclass
class DroneFlightPath:
    base_hub_id: str
    base_coordinate: Coordinate
    total_distance_m: float
    estimated_flight_minutes: float
    targets_inspected: int
    waypoints: List[DroneWaypoint] = field(default_factory=list)
    line_coordinates_3d: List[List[float]] = field(default_factory=list) # [[lon, lat, alt], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_hub_id": self.base_hub_id,
            "base_coordinate": self.base_coordinate.to_dict(),
            "total_distance_m": round(self.total_distance_m, 1),
            "estimated_flight_minutes": round(self.estimated_flight_minutes, 1),
            "targets_inspected": self.targets_inspected,
            "waypoints": [w.to_dict() for w in self.waypoints],
            "line_coordinates_3d": self.line_coordinates_3d,
        }


class InspectionPrioritizer:
    """Computes field inspection priorities and coordinates autonomous drone flights."""

    def __init__(self, cruise_altitude_m: float = 40.0, drone_speed_mps: float = 8.0):
        self.cruise_altitude_m = cruise_altitude_m
        self.drone_speed_mps = drone_speed_mps

    def prioritize_consumers(
        self,
        anomaly_results: Dict[str, AnomalyDetectionResult],
        consumers: Dict[str, ConsumerNode],
    ) -> List[InspectionTarget]:
        """
        Ranks suspicious consumers based on:
        - Anomaly Score
        - Unreported Loss Estimate
        - Criticality (Theft / Tampering > Malfunction > Comm Failure)
        """
        targets = []
        for c_id, res in anomaly_results.items():
            if res.risk_level in ["NORMAL", "LOW"] and res.probable_cause not in ["THEFT_TAMPERING", "METER_MALFUNCTION"]:
                continue

            consumer = consumers.get(c_id)
            if not consumer:
                continue

            # Weightings
            score_weight = res.anomaly_score * 0.45
            cause_bonus = 0.0
            if res.probable_cause == "THEFT_TAMPERING":
                cause_bonus = 35.0
            elif res.probable_cause == "METER_MALFUNCTION":
                cause_bonus = 20.0
            elif res.probable_cause == "COMM_FAILURE":
                cause_bonus = 10.0

            loss_est = max(0.0, res.baseline_mean_kw - res.reported_kw)
            loss_weight = min(25.0, loss_est * 6.0)

            priority_score = score_weight + cause_bonus + loss_weight

            targets.append(
                InspectionTarget(
                    consumer_id=c_id,
                    meter_id=consumer.meter_id,
                    consumer_name=consumer.name,
                    coordinate=consumer.coordinate,
                    building_height_m=consumer.building_height_m,
                    anomaly_score=res.anomaly_score,
                    probable_cause=res.probable_cause,
                    risk_level=res.risk_level,
                    priority_score=priority_score,
                    rank=0,
                    unreported_loss_kw=loss_est,
                    recommended_action=res.recommended_action,
                )
            )

        # Sort descending by priority score
        targets.sort(key=lambda t: t.priority_score, reverse=True)
        for idx, t in enumerate(targets):
            t.rank = idx + 1

        return targets

    def plan_drone_inspection_route(
        self,
        base_hub: TransformerNode,
        targets: List[InspectionTarget],
        max_targets: int = 5,
    ) -> DroneFlightPath:
        """
        Plans a 3D drone trajectory starting from base transformer hub,
        visiting top-priority targets using greedy nearest-neighbor, and returning.
        """
        selected_targets = targets[:max_targets]
        if not selected_targets:
            return DroneFlightPath(
                base_hub_id=base_hub.id,
                base_coordinate=base_hub.coordinate,
                total_distance_m=0.0,
                estimated_flight_minutes=0.0,
                targets_inspected=0,
                waypoints=[],
                line_coordinates_3d=[],
            )

        # Base station coordinate
        base_coord = base_hub.coordinate
        waypoints: List[DroneWaypoint] = []
        path_3d: List[List[float]] = []

        # 1. Takeoff from Hub
        waypoints.append(
            DroneWaypoint(
                lat=base_coord.lat,
                lon=base_coord.lon,
                altitude_m=base_coord.elevation_m,
                action="TAKEOFF",
            )
        )
        path_3d.append([base_coord.lon, base_coord.lat, base_coord.elevation_m])

        # Cruising altitude
        cruise_alt = base_coord.elevation_m + self.cruise_altitude_m
        waypoints.append(
            DroneWaypoint(
                lat=base_coord.lat,
                lon=base_coord.lon,
                altitude_m=cruise_alt,
                action="CRUISE",
            )
        )
        path_3d.append([base_coord.lon, base_coord.lat, cruise_alt])

        # Greedy route planning
        unvisited = list(selected_targets)
        curr_coord = Coordinate(lat=base_coord.lat, lon=base_coord.lon, elevation_m=cruise_alt)
        total_dist_m = 0.0

        while unvisited:
            # Pick nearest target
            nearest = min(unvisited, key=lambda t: curr_coord.distance_to(t.coordinate))
            unvisited.remove(nearest)

            t_coord = nearest.coordinate
            # Cruise point above building
            cruise_waypoint = Coordinate(lat=t_coord.lat, lon=t_coord.lon, elevation_m=cruise_alt)
            total_dist_m += curr_coord.distance_to(cruise_waypoint)
            path_3d.append([cruise_waypoint.lon, cruise_waypoint.lat, cruise_waypoint.elevation_m])

            # Inspection hover altitude (building height + 6m)
            inspect_alt = t_coord.elevation_m + 6.0
            waypoints.append(
                DroneWaypoint(
                    lat=t_coord.lat,
                    lon=t_coord.lon,
                    altitude_m=inspect_alt,
                    action="HOVER_INSPECT",
                    target_id=nearest.consumer_id,
                    hover_duration_sec=30,
                )
            )
            total_dist_m += abs(cruise_alt - inspect_alt) * 2.0
            path_3d.append([t_coord.lon, t_coord.lat, inspect_alt])
            path_3d.append([t_coord.lon, t_coord.lat, cruise_alt])

            curr_coord = cruise_waypoint

        # Return to Hub
        total_dist_m += curr_coord.distance_to(Coordinate(lat=base_coord.lat, lon=base_coord.lon, elevation_m=cruise_alt))
        path_3d.append([base_coord.lon, base_coord.lat, cruise_alt])
        path_3d.append([base_coord.lon, base_coord.lat, base_coord.elevation_m])
        waypoints.append(
            DroneWaypoint(
                lat=base_coord.lat,
                lon=base_coord.lon,
                altitude_m=base_coord.elevation_m,
                action="LAND",
            )
        )

        flight_time_min = (total_dist_m / self.drone_speed_mps + len(selected_targets) * 30.0) / 60.0

        return DroneFlightPath(
            base_hub_id=base_hub.id,
            base_coordinate=base_hub.coordinate,
            total_distance_m=total_dist_m,
            estimated_flight_minutes=flight_time_min,
            targets_inspected=len(selected_targets),
            waypoints=waypoints,
            line_coordinates_3d=path_3d,
        )
