document.addEventListener('DOMContentLoaded', function() {
    const startSyncBtn = document.getElementById('start-sync');
    const stopSyncBtn = document.getElementById('stop-sync');
    const syncStatus = document.getElementById('sync-status');
    const operationsLog = document.getElementById('operations-log');

    // Функция обновления статуса
    async function updateStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            syncStatus.textContent = data.status;
            syncStatus.className = `badge bg-${data.is_running ? 'success' : 'secondary'}`;
            
            // Обновляем лог операций
            if (data.recent_operations && data.recent_operations.length > 0) {
                operationsLog.innerHTML = data.recent_operations
                    .map(op => `
                        <tr>
                            <td>${new Date(op.timestamp).toLocaleString()}</td>
                            <td>${op.operation}</td>
                            <td><span class="badge bg-${op.status === 'success' ? 'success' : 'danger'}">${op.status}</span></td>
                        </tr>
                    `)
                    .join('');
            }
        } catch (error) {
            console.error('Ошибка при получении статуса:', error);
        }
    }

    // Обработчики кнопок
    startSyncBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/sync/start', { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                updateStatus();
            }
        } catch (error) {
            console.error('Ошибка при запуске синхронизации:', error);
        }
    });

    stopSyncBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/sync/stop', { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                updateStatus();
            }
        } catch (error) {
            console.error('Ошибка при остановке синхронизации:', error);
        }
    });

    // Обновляем статус каждые 5 секунд
    updateStatus();
    setInterval(updateStatus, 5000);

    // Обработка формы входа
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                const response = await fetch('/api/auth/login/access-token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        email: loginForm.email.value,
                        password: loginForm.password.value,
                    }),
                });
                const data = await response.json();
                if (response.ok) {
                    localStorage.setItem('token', data.access_token);
                    window.location.href = '/';
                } else {
                    showAlert('danger', data.detail || 'Ошибка входа');
                }
            } catch (error) {
                showAlert('danger', 'Ошибка сервера');
            }
        });
    }

    // Обработка формы регистрации
    const registerForm = document.getElementById('register-form');
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (registerForm.password.value !== registerForm.password_confirm.value) {
                showAlert('danger', 'Пароли не совпадают');
                return;
            }
            try {
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        email: registerForm.email.value,
                        password: registerForm.password.value,
                        company_name: registerForm.company_name.value,
                    }),
                });
                const data = await response.json();
                if (response.ok) {
                    showAlert('success', 'Регистрация успешна');
                    setTimeout(() => {
                        window.location.href = '/login';
                    }, 1500);
                } else {
                    showAlert('danger', data.detail || 'Ошибка регистрации');
                }
            } catch (error) {
                showAlert('danger', 'Ошибка сервера');
            }
        });
    }

    // Обработка выхода
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            localStorage.removeItem('token');
            window.location.href = '/login';
        });
    }

    // Функция для показа уведомлений
    function showAlert(type, message) {
        const alertsContainer = document.querySelector('.messages') || createAlertsContainer();
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        alertsContainer.appendChild(alert);
        setTimeout(() => {
            alert.remove();
        }, 5000);
    }

    function createAlertsContainer() {
        const container = document.createElement('div');
        container.className = 'messages';
        document.querySelector('main').insertBefore(container, document.querySelector('main').firstChild);
        return container;
    }

    // Добавление токена к запросам
    function addAuthHeader(headers = {}) {
        const token = localStorage.getItem('token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    }
}); 