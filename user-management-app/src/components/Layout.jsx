import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';

export default function Layout({ children, user, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);

  const initial = (user?.username || 'U')[0].toUpperCase();

  return (
    <div className="jss1">
      <div className="jss2">
        <header className="MuiPaper-root MuiAppBar-root MuiAppBar-positionFixed MuiAppBar-colorPrimary jss4 MuiPaper-elevation0">
          <div className="MuiToolbar-root MuiToolbar-regular MuiToolbar-gutters">
            <a href="/admin/team/gameday3/" style={{ textDecoration: 'none' }}>
              <img
                src="/static/favicon.png"
                alt="Gameday Stats"
                className="jss11"
                style={{
                  height: 32,
                  width: 'auto',
                  maxWidth: 160,
                  display: 'block',
                  objectFit: 'contain',
                }}
              />
            </a>
            <p className="MuiTypography-root jss5 MuiTypography-body1">USER MANAGEMENT</p>
            <div className="jss9" style={{ flex: 1 }} />
            <div className="dropdown" style={{ position: 'relative' }}>
              <button
                type="button"
                className="MuiAvatar-root MuiAvatar-circle jss16 MuiAvatar-colorDefault"
                style={{ cursor: 'pointer', border: 'none', background: 'transparent' }}
                onClick={(e) => { e.stopPropagation(); e.preventDefault(); setMenuOpen(!menuOpen); }}
                aria-label="account menu"
              >
                {initial}
              </button>
              {menuOpen && (
                <ul
                  className="dropdown-menu dropdown-menu-right"
                  role="menu"
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    display: 'block',
                    marginTop: 4,
                    minWidth: 180,
                  }}
                >
                  <li><a href="/admin/user" role="menuitem">My profile</a></li>
                  <li><Link to="/manage-users" role="menuitem" style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none' }}>Manage Users</Link></li>
                  <li><Link to="/manage-database" role="menuitem" style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none' }}>Manage Database</Link></li>
                  <li role="separator" className="divider" />
                  <li><a href="/logout" role="menuitem">Sign out</a></li>
                </ul>
              )}
            </div>
          </div>
        </header>
        <div className="jss3">{children}</div>
      </div>
    </div>
  );
}
