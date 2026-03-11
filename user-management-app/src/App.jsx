import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import UsersTable from './components/UsersTable';
import AddUserModal from './components/AddUserModal';
import UserPermissions from './components/UserPermissions';
import ManageDatabase from './components/ManageDatabase';
import API from './api';

function UsersPage() {
  const [user, setUser] = useState(null);
  const [accountName, setAccountName] = useState('');
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const [meRes, usersRes] = await Promise.all([
        API.getMe(),
        API.getUsers(),
      ]);
      setUser(meRes.user);
      setAccountName(meRes.account_name);
      setUsers(usersRes.users);
    } catch (err) {
      setError(err.message);
      if (err.message.includes('Not authenticated') || err.message.includes('Admin only')) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
        return;
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>Loading...</div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <p style={{ color: '#BA1A1A' }}>{error}</p>
        <a href="/login">Go to login</a>
      </div>
    );
  }

  return (
    <Layout user={user}>
      {error && <div className="alert alert-danger" style={{ marginBottom: 14 }}>{error}</div>}
      <nav className="MuiTypography-root MuiBreadcrumbs-root jss74 MuiTypography-body1 MuiTypography-colorTextSecondary" aria-label="breadcrumb">
        <ol className="MuiBreadcrumbs-ol" style={{ listStyle: 'none', display: 'flex', padding: 0, margin: 0 }}>
          <li className="MuiBreadcrumbs-li"><span>Accounts</span></li>
          <li aria-hidden="true" className="MuiBreadcrumbs-separator">›</li>
          <li className="MuiBreadcrumbs-li"><span className="jss80">Users</span></li>
        </ol>
      </nav>
      <div className="MuiBox-root jss166 jss75">
        <div className="MuiBox-root jss167">
          <p className="MuiTypography-root jss135 MuiTypography-body1">{accountName}</p>
        </div>
        <div className="MuiBox-root jss170">
          <div className="jss157">
            <div className="jss158">
              <button
                type="button"
                className="MuiButtonBase-root MuiButton-root MuiButton-contained MuiButton-containedPrimary MuiButton-containedSizeLarge MuiButton-sizeLarge MuiButton-disableElevation"
                tabIndex={0}
                onClick={() => setModalOpen(true)}
                style={{
                  padding: '8px 22px',
                  backgroundColor: '#D10B0B',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: '1rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <span>
                  <svg focusable="false" viewBox="0 0 32 32" style={{ width: 20, height: 20 }}>
                    <path d="M17 15L17 8 15 8 15 15 8 15 8 17 15 17 15 24 17 24 17 17 24 17 24 15z" fill="currentColor" />
                  </svg>
                </span>
                <span>New User</span>
              </button>
            </div>
          </div>
        </div>
      </div>
      <UsersTable users={users} currentUserId={user?.id} onRefresh={loadData} />
      <AddUserModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={loadData}
      />
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/manage-users" replace />} />
      <Route path="/manage-users" element={<UsersPage />} />
      <Route path="/manage-users/permissions/:userId" element={<UserPermissions />} />
      <Route path="/manage-database" element={<ManageDatabase />} />
    </Routes>
  );
}
