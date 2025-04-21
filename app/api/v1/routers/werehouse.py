import logging
from typing import List, Optional
import pandas as pd
from io import BytesIO
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query, Request, Form
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
import openpyxl

from app.api import deps
from app.services.allegro import tokens as allegro_tokens
from app.services.allegro.data_access import get_tokens_list, insert_token, delete_token, get_token_by_id
from app.services.allegro.pydantic_models import TokenOfAllegro
from app.services.allegro.pydantic_models import InitializeAuth
from app.models.user import User as UserModel
from app.services.werehouse import manager
from app.services.werehouse.manager import Werehouses

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request, current_user: UserModel = Depends(deps.get_current_user)):
    return templates.TemplateResponse("inventory.html", {
        "request": request,
        "user": current_user
    })

@router.get("/operations", response_class=HTMLResponse)
async def operations_page(request: Request, current_user: UserModel = Depends(deps.get_current_user)):
    return templates.TemplateResponse("operations.html", {
        "request": request,
        "user": current_user
    })

@router.post('/incoming/', summary='Импорт прихода на склад')
async def upload_incoming(
    file: UploadFile = File(...),
    warehouse: Werehouses = Query(Werehouses.A, description="Склад для импорта товаров"),
    sku_col: str = 'sku',
    qty_col: str = 'кол-во',
    ean_col: str = 'EAN/UPC',
    name_col: str = 'Name',
    image_col: str = 'Foto',
    header: int = 1,
    manager: manager.InventoryManager = Depends(manager.get_manager)
):
    if not file.filename.lower().endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail='Неверный формат файла. Ожидается XLS/XLSX.')
    content = await file.read()
    try:
        manager.import_incoming_from_excel(content, warehouse.value, sku_col, qty_col, ean_col, name_col, image_col, header)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({'status': 'success', 'file': file.filename, 'warehouse': warehouse.value})

@router.post('/transfer/', summary='Импорт перемещения между складами')
async def upload_transfer(
    file: UploadFile = File(...),
    from_warehouse: str = Form(..., description="Склад-источник"),
    to_warehouse: str = Form(..., description="Склад-назначение"),
    sku_col: str = Form('sku'),
    qty_col: str = Form('кол-во'),
    header: int = Form(1),
    manager: manager.InventoryManager = Depends(manager.get_manager)
):
    if not file.filename.lower().endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail='Неверный формат файла. Ожидается XLS/XLSX.')
    
    # Проверяем и конвертируем значения складов
    try:
        from_wh = Werehouses(from_warehouse)
        to_wh = Werehouses(to_warehouse)
    except ValueError:
        raise HTTPException(status_code=400, detail='Неверное значение склада')
    
    content = await file.read()
    try:
        manager.import_transfer_from_excel(content, from_wh.value, to_wh.value, sku_col, qty_col, header)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({'status': 'success', 'file': file.filename, 'from': from_wh.value, 'to': to_wh.value})

@router.get('/export/stock/', summary='Экспорт остатков')
async def export_stock(manager: manager.InventoryManager = Depends(manager.get_manager)):
    '''Возвращает XLSX-файл с остатками по складам и общим, включая информацию о товаре и изображения.'''
    df = manager.get_stock_report()
    
    # Переупорядочиваем столбцы
    column_order = ['sku', 'eans']
    # Добавляем столбцы остатков по складам
    stock_columns = [col for col in df.columns if col.startswith('warehouse_')]
    column_order.extend(stock_columns)
    # Добавляем общий остаток
    column_order.append('total')
    # Добавляем изображение и имя последними
    column_order.extend(['image', 'name'])
    
    df = df[column_order]
    
    # Создаем Excel-файл
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        # Сохраняем все данные, включая колонку изображений (но без самих изображений)
        df.to_excel(writer, index=False, sheet_name='Stock')
        
        # Получаем рабочий лист
        worksheet = writer.sheets['Stock']
        
        # Настраиваем автоподбор ширины столбцов
        for column in worksheet.columns:
            max_length = 0
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2) * 1.2  # Увеличиваем ширину на 20%
            worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
        
        # Устанавливаем фиксированную ширину для колонки с изображениями
        if 'image' in df.columns:
            img_column = df.columns.get_loc('image') + 1  # +1 потому что Excel начинает с 1
            worksheet.column_dimensions[openpyxl.utils.get_column_letter(img_column)].width = 25
            
            # Добавляем изображения
            for idx, row in df.iterrows():
                if row.get('image') is not None:
                    try:
                        img = openpyxl.drawing.image.Image(BytesIO(row['image']))
                        img.width = 180
                        img.height = 180
                        
                        # Устанавливаем высоту строки
                        worksheet.row_dimensions[idx + 2].height = 135
                        
                        cell = worksheet.cell(row=idx + 2, column=img_column)
                        worksheet.add_image(img, cell.coordinate)
                    except Exception as e:
                        logging.warning(f"Не удалось добавить изображение для строки {idx + 2}: {str(e)}")
    
    buffer.seek(0)
    headers = {'Content-Disposition': f'attachment; filename="stock_report_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.xlsx"'}
    return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)

@router.get('/export/stock/no-images/', summary='Экспорт остатков без изображений') 
async def export_stock_no_images(manager: manager.InventoryManager = Depends(manager.get_manager)):
    '''Возвращает XLSX-файл с остатками по складам и общим, без изображений.'''
    df = manager.get_stock_report()
    
    # Создаем Excel-файл
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        # Сохраняем данные без колонки изображений
        columns_to_export = [col for col in df.columns if col != 'image']
        df[columns_to_export].to_excel(writer, index=False, sheet_name='Stock')
        
        # Получаем рабочий лист
        worksheet = writer.sheets['Stock']
        
        # Базовое форматирование
        for column in worksheet.columns:
            max_length = 0
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2) * 1.2  # Увеличиваем ширину на 20%
            worksheet.column_dimensions[column[0].column_letter].width = adjusted_width
    
    buffer.seek(0)
    headers = {'Content-Disposition': f'attachment; filename="stock_report_no_images_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.xlsx"'}
    return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)

@router.get('/sales/report/', summary='Отчёт по продажам')
async def sales_report(
    start_date: date = Query(..., description='Начальная дата в формате YYYY-MM-DD'),
    end_date: date = Query(..., description='Конечная дата в формате YYYY-MM-DD'),
    sku: Optional[str] = Query(None, description='Фильтр по SKU'),
    manager: manager.InventoryManager = Depends(manager.get_manager)
):
    '''Возвращает XLSX-файл с логами продаж за указанный период.'''
    df = manager.get_sales_report(start_date, end_date, sku)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales')
    buffer.seek(0)
    filename = f"sales_{start_date}_{end_date}" + (f"_{sku}.xlsx" if sku else '.xlsx')
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)

@router.get('/stock/{sku}', summary='Проверка остатков по SKU')
async def check_stock(
    sku: str,
    manager: manager.InventoryManager = Depends(manager.get_manager)
):
    '''Возвращает остатки по конкретному SKU на всех складах.'''
    stocks = manager.get_stock_by_sku(sku)
    return JSONResponse(content=stocks)

@router.delete('/clear-all/', summary='Удалить все данные')
async def clear_all_data(
    manager: manager.InventoryManager = Depends(manager.get_manager)
):
    '''Удаляет все продукты, остатки и логи продаж из базы данных.'''
    manager.clear_all_data()
    return JSONResponse(content={"message": "Все данные успешно удалены"})
