from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from pa2.storage.database import Database, ProductType, Project, VehicleType


@dataclass(frozen=True, slots=True)
class ProjectView:
    id: str
    name: str
    vehicle_type: str
    product_type: str
    revision: int
    current_snapshot_id: str | None
    current_confirmation_id: str | None


class ProjectService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, name: str, vehicle_name: str, product_name: str) -> ProjectView:
        values = [value.strip() for value in (name, vehicle_name, product_name)]
        if any(not value for value in values):
            raise ValueError("프로젝트명, 차종, 품종을 모두 입력하세요.")
        with self.database.session() as session:
            vehicle = session.scalar(select(VehicleType).where(VehicleType.name == values[1]))
            if vehicle is None:
                vehicle = VehicleType(id=str(uuid.uuid4()), name=values[1])
                session.add(vehicle)
                session.flush()
            product = session.scalar(select(ProductType).where(ProductType.vehicle_type_id == vehicle.id, ProductType.name == values[2]))
            if product is None:
                product = ProductType(id=str(uuid.uuid4()), vehicle_type_id=vehicle.id, name=values[2])
                session.add(product)
                session.flush()
            project = Project(id=str(uuid.uuid4()), vehicle_type_id=vehicle.id, product_type_id=product.id, name=values[0], revision=1)
            session.add(project)
            session.flush()
            return ProjectView(project.id, project.name, vehicle.name, product.name, project.revision, None, None)

    def list(self) -> list[ProjectView]:
        with self.database.session() as session:
            rows = session.execute(
                select(Project, VehicleType, ProductType)
                .join(VehicleType, Project.vehicle_type_id == VehicleType.id)
                .join(ProductType, Project.product_type_id == ProductType.id)
                .where(Project.deleted_at.is_(None))
                .order_by(VehicleType.name, ProductType.name, Project.name)
            ).all()
            return [ProjectView(p.id, p.name, v.name, t.name, p.revision, p.current_snapshot_id, p.current_confirmation_id) for p, v, t in rows]

    def update(self, project_id: str, name: str) -> None:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None or project.deleted_at is not None:
                raise KeyError("프로젝트를 찾을 수 없습니다.")
            project.name = name.strip()
            project.revision += 1

    def delete(self, project_id: str) -> None:
        # Soft deletion preserves independently owned learning cases and shared assets.
        from pa2.storage.database import utcnow
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise KeyError("프로젝트를 찾을 수 없습니다.")
            project.deleted_at = utcnow()

    def vocabularies(self) -> tuple[list[str], list[str]]:
        with self.database.session() as session:
            vehicles = list(session.scalars(select(VehicleType.name).order_by(VehicleType.name)))
            products = list(session.scalars(select(ProductType.name).order_by(ProductType.name)))
            return vehicles, products

