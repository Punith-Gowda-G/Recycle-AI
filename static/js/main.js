document.addEventListener('DOMContentLoaded', () => {
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav-links');
  if (navToggle && nav) {
    navToggle.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
    });
  }

  document.querySelectorAll('.flash-close').forEach(button => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  const imageInput = document.getElementById('image-input');
  const fileName = document.getElementById('file-name');
  if (imageInput && fileName) {
    imageInput.addEventListener('change', () => {
      fileName.textContent = imageInput.files?.[0]?.name || 'Show recyclers what you have';
    });
  }

  document.querySelectorAll('[data-confirm]').forEach(button => {
    button.addEventListener('click', event => {
      if (!window.confirm(button.dataset.confirm || 'Are you sure?')) event.preventDefault();
    });
  });

  const chartData = document.getElementById('monthly-data');
  const chartCanvas = document.getElementById('listingChart');
  if (chartData && chartCanvas && window.Chart) {
    try {
      const data = JSON.parse(chartData.textContent);
      new Chart(chartCanvas, {
        type: 'bar',
        data: {
          labels: data.labels,
          datasets: [{
            label: 'Listings', data: data.values,
            backgroundColor: '#9bc783', hoverBackgroundColor: '#285c3c',
            borderRadius: 7, borderSkipped: false, maxBarThickness: 36
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { displayColors: false } },
          scales: {
            x: { grid: { display: false }, border: { display: false }, ticks: { color: '#899489', font: { family: 'DM Sans', size: 10 } } },
            y: { beginAtZero: true, ticks: { precision: 0, color: '#899489', font: { family: 'DM Sans', size: 10 } }, grid: { color: '#edf1eb' }, border: { display: false } }
          }
        }
      });
    } catch (error) {
      console.error('Could not load listing activity chart.', error);
    }
  }
});

// Lightweight notification polling: no WebSocket service required for the portfolio demo.
(() => {
  const badge = document.getElementById('notification-count');
  if (!badge || !document.body.dataset) return;
  const refresh = async () => {
    try {
      const response = await fetch('/api/notifications', { headers: { 'Accept': 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      badge.textContent = String(data.unread || 0);
      badge.hidden = !data.unread;
    } catch (_) { /* keep the page usable if polling is unavailable */ }
  };
  refresh();
  window.setInterval(refresh, 15000);
})();
