-- Скрипт для исправления Unknown account_names в pending_stock_operations
-- Показывает количество записей с Unknown account_name

SELECT 
    COUNT(*) as total_unknown_accounts,
    COUNT(DISTINCT token_id) as unique_tokens
FROM pending_stock_operations 
WHERE account_name LIKE 'Unknown(%';

-- Показывает примеры записей с Unknown account_name
SELECT 
    id,
    order_id,
    token_id,
    account_name,
    status,
    created_at
FROM pending_stock_operations 
WHERE account_name LIKE 'Unknown(%'
ORDER BY created_at DESC
LIMIT 10;

-- Для обновления записей (раскомментируйте после проверки):
-- UPDATE pending_stock_operations 
-- SET account_name = 'Правильное имя аккаунта', updated_at = NOW()
-- WHERE token_id = '52361c88-e421-427d-a68c-37ad0fce2ee0';