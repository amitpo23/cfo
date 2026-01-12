"""
CRM API routes
Handles CRM entities, folders, and views
"""
from fastapi import APIRouter, Depends, Query
from typing import List, Optional

from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    EntityRequest, EntityResponse, FolderResponse
)
from ..dependencies import get_current_user, get_sumit_integration

router = APIRouter()


# ==================== Entities ====================

@router.post("/entities", response_model=EntityResponse)
async def create_entity(
    entity: EntityRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create CRM entity"""
    async with sumit:
        return await sumit.create_entity(entity)


@router.get("/entities/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get CRM entity details"""
    async with sumit:
        return await sumit.get_entity(entity_id)


@router.get("/entities", response_model=List[EntityResponse])
async def list_entities(
    folder_id: str = Query(..., description="Folder ID"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List CRM entities in folder"""
    async with sumit:
        return await sumit.list_entities(folder_id, limit, offset)


@router.put("/entities/{entity_id}", response_model=EntityResponse)
async def update_entity(
    entity_id: str,
    entity: EntityRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Update CRM entity"""
    async with sumit:
        return await sumit.update_entity(entity_id, entity)


@router.post("/entities/{entity_id}/archive")
async def archive_entity(
    entity_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Archive CRM entity"""
    async with sumit:
        return await sumit.archive_entity(entity_id)


@router.delete("/entities/{entity_id}")
async def delete_entity(
    entity_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Delete CRM entity"""
    async with sumit:
        return await sumit.delete_entity(entity_id)


@router.get("/entities/{entity_id}/usage-count")
async def count_entity_usage(
    entity_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Count entity usage in system"""
    async with sumit:
        count = await sumit.count_entity_usage(entity_id)
        return {"entity_id": entity_id, "usage_count": count}


@router.get("/entities/{entity_id}/print")
async def get_entity_print_html(
    entity_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get entity as printable HTML"""
    from fastapi.responses import HTMLResponse
    
    async with sumit:
        html = await sumit.get_entity_print_html(entity_id)
        return HTMLResponse(content=html)


# ==================== Folders ====================

@router.get("/folders/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get CRM folder details and schema"""
    async with sumit:
        return await sumit.get_folder(folder_id)


@router.get("/folders", response_model=List[FolderResponse])
async def list_folders(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List all CRM folders"""
    async with sumit:
        return await sumit.list_folders()


# ==================== Views ====================

@router.get("/folders/{folder_id}/views")
async def list_views(
    folder_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List views for a folder"""
    async with sumit:
        views = await sumit.list_views(folder_id)
        return {"folder_id": folder_id, "views": views}
