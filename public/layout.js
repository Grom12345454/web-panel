const NAV_ITEMS = [
  ['index.html', '⌂', 'Dashboard'],
  ['traffic.html', '⌁', 'Traffic'],
  ['alerts.html', '!', 'Alerts'],
  ['devices.html', '◈', 'Devices'],
  ['ai.html', '✦', 'AI Analysis'],
  ['firewall.html', '⛨', 'Firewall'],
  ['settings.html', '⚙', 'Settings'],
];

function renderSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  const currentPage = location.pathname.split('/').pop() || 'index.html';
  const links = NAV_ITEMS.map(([href, icon, label]) => `
    <a class="${currentPage === href ? 'active' : ''}" href="${href}">
      <i class="ico">${icon}</i>
      <span>${label}</span>
    </a>
  `).join('');

  sidebar.innerHTML = `
    <div class="logo">
      <div class="logoMark"></div>
      <div>
        <b>WIRESHARK AI</b>
        <small>SOC ADMIN CONSOLE</small>
      </div>
    </div>

    <div class="navGroup">Security Operations</div>
    <nav class="nav" aria-label="Security Operations">
      ${links}
    </nav>

    <div class="sidebarBottom">
      <div class="conn"><i></i> BACKEND CONNECTED</div>
      <div class="server">${location.origin}</div>
    </div>
  `;
}

renderSidebar();
