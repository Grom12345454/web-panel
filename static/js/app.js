(() => {
    const mobileBtn = document.querySelector('[data-mobile-nav]');
    const sidebar = document.querySelector('.sidebar');
    if (mobileBtn && sidebar) {
        mobileBtn.addEventListener('click', () => {
            sidebar.style.display = sidebar.style.display === 'block' ? '' : 'block';
            sidebar.style.position = 'fixed';
            sidebar.style.left = '0';
            sidebar.style.top = '0';
            sidebar.style.bottom = '0';
            sidebar.style.zIndex = '80';
            sidebar.style.boxShadow = '24px 0 70px rgba(0,0,0,.35)';
        });
    }

    document.querySelectorAll('[data-tilt]').forEach((card) => {
        if (window.matchMedia('(pointer: coarse)').matches) return;
        card.addEventListener('pointermove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width - 0.5;
            const y = (e.clientY - rect.top) / rect.height - 0.5;
            card.style.transform = `perspective(1000px) rotateX(${(-y * 5).toFixed(2)}deg) rotateY(${(x * 7).toFixed(2)}deg) translateZ(2px)`;
        });
        card.addEventListener('pointerleave', () => {
            card.style.transform = '';
        });
    });

    document.querySelectorAll('[data-dismiss]').forEach((el) => {
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transform = 'translateY(8px)';
            setTimeout(() => el.remove(), 260);
        }, 4200);
    });

    document.querySelectorAll('[data-confirm]').forEach((form) => {
        form.addEventListener('submit', (e) => {
            const message = form.getAttribute('data-confirm');
            if (message && !window.confirm(message)) e.preventDefault();
        });
    });
})();

(() => {
    const container = document.getElementById('quota-days');
    const addBtn = document.getElementById('add-quota-day');
    const hint = document.getElementById('quota-days-hint');
    const form = document.getElementById('quota-create-form');
    if (!container || !addBtn || !form) return;

    let nextIndex = 0;

    const updateHint = () => {
        const count = container.querySelectorAll('[data-quota-day]').length;
        if (hint) hint.textContent = `Добавлено дат: ${count}`;
    };

    const addDay = (dateValue = '', placesValue = '') => {
        const index = nextIndex++;
        const row = document.createElement('div');
        row.className = 'quota-day-row';
        row.dataset.quotaDay = '1';
        row.innerHTML = `
            <div class="field">
                <div class="quota-day-number">Дата #${container.children.length + 1}</div>
                <input class="input" name="day_date_${index}" type="date" value="${dateValue}" required>
            </div>
            <div class="field">
                <div class="quota-day-number">Мест на дату</div>
                <input class="input" name="day_places_${index}" type="number" min="1" value="${placesValue}" required placeholder="20">
            </div>
            <button class="btn btn-soft btn-remove-day" type="button" aria-label="Удалить дату">Удалить</button>
        `;
        row.querySelector('.btn-remove-day').addEventListener('click', () => {
            row.remove();
            [...container.children].forEach((el, i) => {
                const number = el.querySelector('.quota-day-number');
                if (number) number.textContent = `Дата #${i + 1}`;
            });
            updateHint();
        });
        container.appendChild(row);
        updateHint();
    };

    addBtn.addEventListener('click', () => addDay());
    addDay();

    form.addEventListener('submit', (event) => {
        if (!container.querySelector('[data-quota-day]')) {
            event.preventDefault();
            alert('Добавьте хотя бы одну дату мероприятия.');
        }
    });
})();
