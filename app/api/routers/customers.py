"""
Enrutador REST para el recurso Customer.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_db
from app.core.security import get_api_key
from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.models.relationships import CustomerRelationship
from app.schemas.collections import (
    CollectionAddressCreate,
    CollectionAddressResponse,
    CollectionAddressUpdate,
    CollectionEmailCreate,
    CollectionEmailResponse,
    CollectionEmailUpdate,
    CollectionPhoneCreate,
    CollectionPhoneResponse,
    CollectionPhoneUpdate,
    SoftDeleteBody,
)
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerResponseFull, CustomerUpdate
from app.schemas.relationships import CustomerRelationshipResponse
from app.services.data_cleaning import clean_phone_number

router = APIRouter(tags=["Customers"], dependencies=[Depends(get_api_key)])


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_customer_or_404(identification: str, db: Session) -> Customer:
    cliente = db.execute(
        select(Customer).where(Customer.identification == identification)
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con identificación '{identification}' no encontrado.",
        )
    return cliente


def _get_phone_or_404(identification: str, phone_id: int, db: Session) -> CollectionPhone:
    customer = _get_customer_or_404(identification, db)
    phone = db.execute(
        select(CollectionPhone).where(
            CollectionPhone.id == phone_id,
            CollectionPhone.customer_id == customer.id,
        )
    ).scalar_one_or_none()
    if not phone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Teléfono con ID {phone_id} no encontrado para este cliente.")
    return phone


def _get_email_or_404(identification: str, email_id: int, db: Session) -> CollectionEmail:
    customer = _get_customer_or_404(identification, db)
    email = db.execute(
        select(CollectionEmail).where(
            CollectionEmail.id == email_id,
            CollectionEmail.customer_id == customer.id,
        )
    ).scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Correo con ID {email_id} no encontrado para este cliente.")
    return email


def _get_address_or_404(identification: str, address_id: int, db: Session) -> CollectionAddress:
    customer = _get_customer_or_404(identification, db)
    address = db.execute(
        select(CollectionAddress).where(
            CollectionAddress.id == address_id,
            CollectionAddress.customer_id == customer.id,
        )
    ).scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Dirección con ID {address_id} no encontrada para este cliente.")
    return address


# ---------------------------------------------------------------------------
# Response schemas locales
# ---------------------------------------------------------------------------

class IdentificationListResponse(BaseModel):
    identifications: List[str]


class BatchRequest(BaseModel):
    identifications: List[str] = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# POST / — Crear cliente
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo cliente",
)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    nuevo_cliente = Customer(
        identification=payload.identification,
        first_name=payload.first_name,
        last_name=payload.last_name,
        gender=payload.gender,
        birth_date=payload.birth_date,
        birth_place=payload.birth_place,
        nationality=payload.nationality,
        civil_status=payload.civil_status,
        profession=payload.profession,
    )
    db.add(nuevo_cliente)
    try:
        db.commit()
        db.refresh(nuevo_cliente)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un cliente con la identificación '{payload.identification}'.",
        )
    return nuevo_cliente


# ---------------------------------------------------------------------------
# GET / — Listar clientes
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[CustomerResponse], summary="Listar todos los clientes")
def list_customers(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[Customer]:
    return list(db.execute(select(Customer).offset(skip).limit(limit).order_by(Customer.id)).scalars().all())


# ---------------------------------------------------------------------------
# GET /search — Búsqueda por nombre y/o geografía → lista de cédulas
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    response_model=IdentificationListResponse,
    summary="Buscar clientes por nombre o geografía",
    description=(
        "Retorna una lista de cédulas que coinciden con los filtros. "
        "Todos los parámetros son opcionales pero se requiere al menos uno. "
        "Búsqueda de nombre parcial sobre first_name y last_name. "
        "Búsqueda geográfica sobre las direcciones registradas. Máximo 500 resultados."
    ),
)
def search_customers(
    name: Optional[str] = Query(None, min_length=2, description="Búsqueda parcial en nombre y apellido"),
    province: Optional[str] = Query(None),
    canton: Optional[str] = Query(None),
    parish: Optional[str] = Query(None),
    neighborhood: Optional[str] = Query(None),
    address_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> IdentificationListResponse:
    if not any([name, province, canton, parish, neighborhood, address_type]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Se requiere al menos un parámetro de búsqueda.",
        )

    stmt = select(Customer.identification).distinct()

    if name:
        pattern = f"%{name}%"
        stmt = stmt.where(or_(
            Customer.first_name.ilike(pattern),
            Customer.last_name.ilike(pattern),
        ))

    if any([province, canton, parish, neighborhood, address_type]):
        stmt = stmt.join(CollectionAddress, CollectionAddress.customer_id == Customer.id)
        if province:
            stmt = stmt.where(CollectionAddress.province.ilike(f"%{province}%"))
        if canton:
            stmt = stmt.where(or_(
                CollectionAddress.city.ilike(f"%{canton}%"),
                CollectionAddress.canton.ilike(f"%{canton}%"),
            ))
        if parish:
            stmt = stmt.where(CollectionAddress.parish.ilike(f"%{parish}%"))
        if neighborhood:
            stmt = stmt.where(CollectionAddress.neighborhood.ilike(f"%{neighborhood}%"))
        if address_type:
            stmt = stmt.where(CollectionAddress.address_type.ilike(f"%{address_type}%"))

    stmt = stmt.limit(500)
    rows = db.execute(stmt).scalars().all()
    return IdentificationListResponse(identifications=list(rows))


# ---------------------------------------------------------------------------
# POST /batch — Lookup batch por array de cédulas
# ---------------------------------------------------------------------------

@router.post(
    "/batch",
    response_model=List[CustomerResponseFull],
    summary="Obtener múltiples clientes por cédulas (batch)",
    description=(
        "Recibe un array de cédulas y retorna el perfil completo de cada cliente encontrado. "
        "Las cédulas no encontradas se omiten silenciosamente."
    ),
)
def batch_customers(
    body: Annotated[BatchRequest, Body()],
    db: Session = Depends(get_db),
) -> List[Customer]:
    stmt = (
        select(Customer)
        .where(Customer.identification.in_(body.identifications))
        .options(
            selectinload(Customer.phones),
            selectinload(Customer.addresses),
            selectinload(Customer.emails),
            selectinload(Customer.financial_information),
            selectinload(Customer.equifax_queries),
            selectinload(Customer.relationships),
        )
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# GET /by-phone/{phone_number} — Buscar cliente por teléfono
# ---------------------------------------------------------------------------

@router.get(
    "/by-phone/{phone_number}",
    response_model=CustomerResponse,
    summary="Buscar cliente por número de teléfono",
)
def get_customer_by_phone(phone_number: str, db: Session = Depends(get_db)) -> Customer:
    normalized = clean_phone_number(phone_number)
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"El número '{phone_number}' no es válido.")
    stmt = (
        select(Customer)
        .join(CollectionPhone, CollectionPhone.customer_id == Customer.id)
        .where(CollectionPhone.phone_number == normalized)
        .limit(1)
    )
    cliente = db.execute(stmt).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No se encontró ningún cliente con el teléfono '{normalized}'.")
    return cliente


# ---------------------------------------------------------------------------
# GET /{identification} — Datos básicos
# ---------------------------------------------------------------------------

@router.get("/{identification}", response_model=CustomerResponse, summary="Obtener cliente por cédula o RUC")
def get_customer(identification: str, db: Session = Depends(get_db)) -> Customer:
    return _get_customer_or_404(identification, db)


# ---------------------------------------------------------------------------
# GET /{identification}/full — Cliente con todas sus relaciones
# ---------------------------------------------------------------------------

@router.get(
    "/{identification}/full",
    response_model=CustomerResponseFull,
    summary="Obtener cliente con todas sus relaciones",
)
def get_customer_full(identification: str, db: Session = Depends(get_db)) -> Customer:
    stmt = (
        select(Customer)
        .where(Customer.identification == identification)
        .options(
            selectinload(Customer.phones),
            selectinload(Customer.addresses),
            selectinload(Customer.emails),
            selectinload(Customer.financial_information),
            selectinload(Customer.equifax_queries),
            selectinload(Customer.relationships),
        )
    )
    cliente = db.execute(stmt).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con identificación '{identification}' no encontrado.")
    return cliente


# ---------------------------------------------------------------------------
# PHONES — GET / POST / PATCH / DELETE
# ---------------------------------------------------------------------------

@router.get("/{identification}/phones", response_model=List[CollectionPhoneResponse],
            summary="Listar teléfonos de un cliente")
def list_customer_phones(
    identification: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    cliente = _get_customer_or_404(identification, db)
    stmt = (select(CollectionPhone).where(CollectionPhone.customer_id == cliente.id)
            .order_by(CollectionPhone.created_at.desc()).offset(skip).limit(limit))
    return list(db.execute(stmt).scalars().all())


@router.post("/{identification}/phones", response_model=CollectionPhoneResponse,
             status_code=status.HTTP_201_CREATED, summary="Agregar teléfono")
def add_customer_phone(
    identification: str,
    payload: CollectionPhoneCreate,
    db: Session = Depends(get_db),
) -> CollectionPhone:
    cliente = _get_customer_or_404(identification, db)
    if db.execute(select(CollectionPhone).where(
        CollectionPhone.customer_id == cliente.id,
        CollectionPhone.phone_number == payload.phone_number,
    )).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"El número '{payload.phone_number}' ya está registrado.")
    phone = CollectionPhone(
        customer_id=cliente.id,
        phone_number=payload.phone_number,
        phone_type=payload.phone_type,
        country_code=payload.country_code,
        source=payload.source,
        created_by=payload.created_by,
        created_source=payload.created_source,
    )
    db.add(phone)
    db.commit()
    db.refresh(phone)
    return phone


@router.patch("/{identification}/phones/{phone_id}", response_model=CollectionPhoneResponse,
              summary="Actualizar teléfono")
def update_customer_phone(
    identification: str,
    phone_id: int,
    payload: CollectionPhoneUpdate,
    db: Session = Depends(get_db),
) -> CollectionPhone:
    phone = _get_phone_or_404(identification, phone_id, db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(phone, k, v)
    phone.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(phone)
    return phone


@router.delete("/{identification}/phones/{phone_id}", status_code=status.HTTP_200_OK,
               response_model=CollectionPhoneResponse, summary="Inactivar teléfono (soft delete)")
def delete_customer_phone(
    identification: str,
    phone_id: int,
    body: SoftDeleteBody = Body(default=SoftDeleteBody()),
    db: Session = Depends(get_db),
) -> CollectionPhone:
    phone = _get_phone_or_404(identification, phone_id, db)
    phone.is_active = False
    phone.deleted_at = datetime.now(timezone.utc)
    phone.deleted_by = body.deleted_by
    phone.deleted_source = body.deleted_source
    db.commit()
    db.refresh(phone)
    return phone


# ---------------------------------------------------------------------------
# EMAILS — GET / POST / PATCH / DELETE
# ---------------------------------------------------------------------------

@router.get("/{identification}/emails", response_model=List[CollectionEmailResponse],
            summary="Listar correos de un cliente")
def list_customer_emails(
    identification: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    cliente = _get_customer_or_404(identification, db)
    stmt = (select(CollectionEmail).where(CollectionEmail.customer_id == cliente.id)
            .order_by(CollectionEmail.created_at.desc()).offset(skip).limit(limit))
    return list(db.execute(stmt).scalars().all())


@router.post("/{identification}/emails", response_model=CollectionEmailResponse,
             status_code=status.HTTP_201_CREATED, summary="Agregar correo")
def add_customer_email(
    identification: str,
    payload: CollectionEmailCreate,
    db: Session = Depends(get_db),
) -> CollectionEmail:
    cliente = _get_customer_or_404(identification, db)
    if db.execute(select(CollectionEmail).where(
        CollectionEmail.customer_id == cliente.id,
        CollectionEmail.email_address == payload.email_address,
    )).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"El correo '{payload.email_address}' ya está registrado.")
    email = CollectionEmail(
        customer_id=cliente.id,
        email_address=payload.email_address,
        is_active=payload.is_active,
        source=payload.source,
        created_by=payload.created_by,
        created_source=payload.created_source,
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


@router.patch("/{identification}/emails/{email_id}", response_model=CollectionEmailResponse,
              summary="Actualizar correo")
def update_customer_email(
    identification: str,
    email_id: int,
    payload: CollectionEmailUpdate,
    db: Session = Depends(get_db),
) -> CollectionEmail:
    email = _get_email_or_404(identification, email_id, db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(email, k, v)
    email.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(email)
    return email


@router.delete("/{identification}/emails/{email_id}", status_code=status.HTTP_200_OK,
               response_model=CollectionEmailResponse, summary="Inactivar correo (soft delete)")
def delete_customer_email(
    identification: str,
    email_id: int,
    body: SoftDeleteBody = Body(default=SoftDeleteBody()),
    db: Session = Depends(get_db),
) -> CollectionEmail:
    email = _get_email_or_404(identification, email_id, db)
    email.is_active = False
    email.deleted_at = datetime.now(timezone.utc)
    email.deleted_by = body.deleted_by
    email.deleted_source = body.deleted_source
    db.commit()
    db.refresh(email)
    return email


# ---------------------------------------------------------------------------
# ADDRESSES — GET / POST / PATCH / DELETE
# ---------------------------------------------------------------------------

@router.get("/{identification}/addresses", response_model=List[CollectionAddressResponse],
            summary="Listar direcciones de un cliente")
def list_customer_addresses(
    identification: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    cliente = _get_customer_or_404(identification, db)
    stmt = (select(CollectionAddress).where(CollectionAddress.customer_id == cliente.id)
            .order_by(CollectionAddress.created_at.desc()).offset(skip).limit(limit))
    return list(db.execute(stmt).scalars().all())


@router.post("/{identification}/addresses", response_model=CollectionAddressResponse,
             status_code=status.HTTP_201_CREATED, summary="Agregar dirección")
def add_customer_address(
    identification: str,
    payload: CollectionAddressCreate,
    db: Session = Depends(get_db),
) -> CollectionAddress:
    cliente = _get_customer_or_404(identification, db)
    addr = CollectionAddress(
        customer_id=cliente.id,
        address_line=payload.address_line,
        province=payload.province,
        city=payload.city,
        canton=payload.canton,
        parish=payload.parish,
        neighborhood=payload.neighborhood,
        address_type=payload.address_type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        source=payload.source,
        created_by=payload.created_by,
        created_source=payload.created_source,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


@router.patch("/{identification}/addresses/{address_id}", response_model=CollectionAddressResponse,
              summary="Actualizar dirección")
def update_customer_address(
    identification: str,
    address_id: int,
    payload: CollectionAddressUpdate,
    db: Session = Depends(get_db),
) -> CollectionAddress:
    addr = _get_address_or_404(identification, address_id, db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(addr, k, v)
    addr.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(addr)
    return addr


@router.delete("/{identification}/addresses/{address_id}", status_code=status.HTTP_200_OK,
               response_model=CollectionAddressResponse, summary="Inactivar dirección (soft delete)")
def delete_customer_address(
    identification: str,
    address_id: int,
    body: SoftDeleteBody = Body(default=SoftDeleteBody()),
    db: Session = Depends(get_db),
) -> CollectionAddress:
    addr = _get_address_or_404(identification, address_id, db)
    addr.is_active = False
    addr.deleted_at = datetime.now(timezone.utc)
    addr.deleted_by = body.deleted_by
    addr.deleted_source = body.deleted_source
    db.commit()
    db.refresh(addr)
    return addr


# ---------------------------------------------------------------------------
# RELATIONSHIPS — GET
# ---------------------------------------------------------------------------

@router.get("/{identification}/relationships", response_model=List[CustomerRelationshipResponse],
            summary="Listar relaciones familiares")
def list_customer_relationships(
    identification: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    cliente = _get_customer_or_404(identification, db)
    stmt = (select(CustomerRelationship).where(CustomerRelationship.customer_id == cliente.id)
            .order_by(CustomerRelationship.id).offset(skip).limit(limit))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# PATCH /{identification} — Actualización parcial del cliente
# ---------------------------------------------------------------------------

@router.patch("/{identification}", response_model=CustomerResponse,
              summary="Actualizar parcialmente un cliente")
def update_customer(
    identification: str,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
) -> Customer:
    cliente = _get_customer_or_404(identification, db)
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(cliente, campo, valor)
    db.commit()
    db.refresh(cliente)
    return cliente


# ---------------------------------------------------------------------------
# DELETE /{identification} — Eliminar cliente (cascade físico)
# ---------------------------------------------------------------------------

@router.delete("/{identification}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Eliminar un cliente")
def delete_customer(identification: str, db: Session = Depends(get_db)) -> None:
    cliente = _get_customer_or_404(identification, db)
    db.delete(cliente)
    db.commit()
