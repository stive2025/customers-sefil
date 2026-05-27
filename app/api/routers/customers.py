"""
Enrutador REST para el recurso Customer.
Implementa los endpoints CRUD completos con paginación y manejo de errores.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_db
from app.core.security import get_api_key
from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.models.relationships import CustomerRelationship
from app.schemas.collections import CollectionAddressResponse, CollectionEmailResponse, CollectionPhoneCreate, CollectionPhoneResponse
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerResponseFull, CustomerUpdate
from app.schemas.relationships import CustomerRelationshipResponse

# El prefix base "/api/v1/customers" se define en main.py al incluir el router.
# dependencies=[Depends(get_api_key)] protege todos los endpoints del router
# sin necesidad de añadir la dependencia manualmente en cada función.
router = APIRouter(tags=["Customers"], dependencies=[Depends(get_api_key)])


# ---------------------------------------------------------------------------
# POST / — Crear cliente
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo cliente",
    description="Registra un nuevo cliente en el sistema. La `identificacion` (cédula/RUC) debe ser única.",
)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
) -> Customer:
    """
    Crea un nuevo registro de Customer en la base de datos.
    Retorna 409 si la identificación ya existe.
    """
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
# GET / — Listar clientes (con paginación)
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=List[CustomerResponse],
    summary="Listar todos los clientes",
    description="Retorna una lista paginada de clientes. Usa `skip` y `limit` para paginar.",
)
def list_customers(
    skip: int = Query(default=0, ge=0, description="Número de registros a omitir"),
    limit: int = Query(default=20, ge=1, le=100, description="Máximo de registros a retornar"),
    db: Session = Depends(get_db),
) -> List[Customer]:
    """Lista todos los clientes con paginación básica por offset."""
    stmt = select(Customer).offset(skip).limit(limit).order_by(Customer.id)
    clientes = db.execute(stmt).scalars().all()
    return list(clientes)


# ---------------------------------------------------------------------------
# GET /search — Búsqueda por nombre o identification (debe ir ANTES de /{id})
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    response_model=List[CustomerResponse],
    summary="Buscar clientes",
    description=(
        "Busca clientes por cédula/RUC exacto o por coincidencia parcial en "
        "nombre y apellido. Mínimo 3 caracteres. Máximo 20 resultados."
    ),
)
def search_customers(
    q: str = Query(..., min_length=3, description="Término de búsqueda"),
    db: Session = Depends(get_db),
) -> List[Customer]:
    """Búsqueda combinada: identification exacto OR ilike en first_name / last_name."""
    pattern = f"%{q}%"
    stmt = (
        select(Customer)
        .where(
            or_(
                Customer.identification == q,
                Customer.first_name.ilike(pattern),
                Customer.last_name.ilike(pattern),
            )
        )
        .order_by(Customer.last_name, Customer.first_name)
        .limit(20)
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# GET /by/{identification} — Obtener cliente por documento (cédula / RUC)
# ---------------------------------------------------------------------------
# Se usa el prefijo /by/ para evitar colisión con GET /{customer_id} (entero).

@router.get(
    "/by/{identification}",
    response_model=CustomerResponse,
    summary="Obtener cliente por documento",
    description="Retorna el cliente exacto cuya cédula o RUC coincide. Retorna 404 si no existe.",
)
def get_customer_by_identification(
    identification: str,
    db: Session = Depends(get_db),
) -> Customer:
    stmt = select(Customer).where(Customer.identification == identification)
    cliente = db.execute(stmt).scalar_one_or_none()
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con identificación '{identification}' no encontrado.",
        )
    return cliente


# ---------------------------------------------------------------------------
# GET /{customer_id} — Obtener cliente por ID (respuesta simple)
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Obtener cliente por ID",
    description="Retorna los datos básicos de un cliente. Retorna 404 si no existe.",
)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
) -> Customer:
    """Busca un Customer por su llave primaria."""
    cliente = db.get(Customer, customer_id)
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con ID {customer_id} no encontrado.",
        )
    return cliente


# ---------------------------------------------------------------------------
# GET /{customer_id}/full — Obtener cliente con todas sus relaciones
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}/full",
    response_model=CustomerResponseFull,
    summary="Obtener cliente con todas sus relaciones",
    description=(
        "Retorna el detalle completo del cliente incluyendo teléfonos, "
        "direcciones, emails, información financiera y consultas Equifax."
    ),
)
def get_customer_full(
    customer_id: int,
    db: Session = Depends(get_db),
) -> Customer:
    """Busca un Customer por ID y carga todas sus relaciones."""
    stmt = (
        select(Customer)
        .where(Customer.id == customer_id)
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con ID {customer_id} no encontrado.",
        )
    return cliente


# ---------------------------------------------------------------------------
# GET /{customer_id}/phones — Teléfonos paginados
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}/phones",
    response_model=List[CollectionPhoneResponse],
    summary="Listar teléfonos de un cliente",
    description="Retorna los teléfonos del cliente con paginación. Ordenados por fecha de creación descendente.",
)
def list_customer_phones(
    customer_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con ID {customer_id} no encontrado.")
    stmt = (
        select(CollectionPhone)
        .where(CollectionPhone.customer_id == customer_id)
        .order_by(CollectionPhone.created_at.desc())
        .offset(skip).limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# GET /{customer_id}/emails — Correos paginados
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}/emails",
    response_model=List[CollectionEmailResponse],
    summary="Listar correos de un cliente",
    description="Retorna los correos electrónicos del cliente con paginación.",
)
def list_customer_emails(
    customer_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con ID {customer_id} no encontrado.")
    stmt = (
        select(CollectionEmail)
        .where(CollectionEmail.customer_id == customer_id)
        .order_by(CollectionEmail.created_at.desc())
        .offset(skip).limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# GET /{customer_id}/addresses — Direcciones paginadas
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}/addresses",
    response_model=List[CollectionAddressResponse],
    summary="Listar direcciones de un cliente",
    description="Retorna las direcciones del cliente con paginación.",
)
def list_customer_addresses(
    customer_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con ID {customer_id} no encontrado.")
    stmt = (
        select(CollectionAddress)
        .where(CollectionAddress.customer_id == customer_id)
        .order_by(CollectionAddress.created_at.desc())
        .offset(skip).limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# GET /{customer_id}/relationships — Relaciones familiares paginadas
# ---------------------------------------------------------------------------

@router.get(
    "/{customer_id}/relationships",
    response_model=List[CustomerRelationshipResponse],
    summary="Listar relaciones familiares de un cliente",
    description="Retorna las relaciones familiares del cliente con paginación.",
)
def list_customer_relationships(
    customer_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list:
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con ID {customer_id} no encontrado.")
    stmt = (
        select(CustomerRelationship)
        .where(CustomerRelationship.customer_id == customer_id)
        .order_by(CustomerRelationship.id)
        .offset(skip).limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# DELETE /{customer_id}/phones/{phone_id} — Eliminar teléfono
# ---------------------------------------------------------------------------

@router.delete(
    "/{customer_id}/phones/{phone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un teléfono de un cliente",
    description="Elimina permanentemente un teléfono del cliente. Retorna 404 si el cliente o el teléfono no existen.",
)
def delete_customer_phone(
    customer_id: int,
    phone_id: int,
    db: Session = Depends(get_db),
) -> None:
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cliente con ID {customer_id} no encontrado.")
    stmt = select(CollectionPhone).where(
        CollectionPhone.id == phone_id,
        CollectionPhone.customer_id == customer_id,
    )
    phone = db.execute(stmt).scalar_one_or_none()
    if not phone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Teléfono con ID {phone_id} no encontrado para este cliente.")
    db.delete(phone)
    db.commit()


# ---------------------------------------------------------------------------
# POST /by/{identification}/phones — Agregar teléfono por cédula
# ---------------------------------------------------------------------------

@router.post(
    "/by/{identification}/phones",
    response_model=CollectionPhoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar teléfono a un cliente por cédula",
    description="Agrega un nuevo número de teléfono al cliente identificado por su cédula o RUC. Retorna 404 si no existe, 409 si el número ya está registrado.",
)
def add_phone_by_identification(
    identification: str,
    payload: CollectionPhoneCreate,
    db: Session = Depends(get_db),
) -> CollectionPhone:
    stmt = select(Customer).where(Customer.identification == identification)
    cliente = db.execute(stmt).scalar_one_or_none()
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con identificación '{identification}' no encontrado.",
        )

    duplicado = db.execute(
        select(CollectionPhone).where(
            CollectionPhone.customer_id == cliente.id,
            CollectionPhone.phone_number == payload.phone_number,
        )
    ).scalar_one_or_none()
    if duplicado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El número '{payload.phone_number}' ya está registrado para este cliente.",
        )

    phone = CollectionPhone(
        customer_id=cliente.id,
        phone_number=payload.phone_number,
        phone_type=payload.phone_type,
        country_code=payload.country_code,
        source=payload.source,
    )
    db.add(phone)
    db.commit()
    db.refresh(phone)
    return phone


# ---------------------------------------------------------------------------
# PATCH /{customer_id} — Actualización parcial
# ---------------------------------------------------------------------------

@router.patch(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Actualizar parcialmente un cliente",
    description="Actualiza solo los campos proporcionados. Los campos omitidos no se modifican.",
)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
) -> Customer:
    """
    Aplica una actualización parcial (PATCH) sobre un Customer existente.
    Solo modifica los campos que vienen explícitamente en el body.
    """
    cliente = db.get(Customer, customer_id)
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con ID {customer_id} no encontrado.",
        )

    # Extraer solo los campos enviados (excluir los que no se enviaron)
    campos_a_actualizar = payload.model_dump(exclude_unset=True)
    for campo, valor in campos_a_actualizar.items():
        setattr(cliente, campo, valor)

    db.commit()
    db.refresh(cliente)
    return cliente


# ---------------------------------------------------------------------------
# DELETE /{customer_id} — Eliminar cliente
# ---------------------------------------------------------------------------

@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un cliente",
    description="Elimina permanentemente un cliente y todos sus datos relacionados (cascade).",
)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Elimina un Customer por ID. Las relaciones se borran por CASCADE."""
    cliente = db.get(Customer, customer_id)
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con ID {customer_id} no encontrado.",
        )

    db.delete(cliente)
    db.commit()