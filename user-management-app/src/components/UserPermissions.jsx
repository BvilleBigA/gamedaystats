import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import Layout from './Layout';
import API from '../api';

export default function UserPermissions() {
  const { userId } = useParams();
  const [user, setUser] = useState(null);
  const [targetUser, setTargetUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [schools, setSchools] = useState([]);
  const [schoolId, setSchoolId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState(null);

  const loadPermissions = async () => {
    if (!userId) return;
    setLoading(true);
    setError('');
    try {
      const [meRes, permRes] = await Promise.all([
        API.getMe(),
        API.getPermissions(userId),
      ]);
      setUser(meRes.user);
      setPermissions(permRes.permissions || []);
      setTargetUser(permRes.user || null);
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

  const loadSchools = async () => {
    try {
      const res = await API.getSchools();
      setSchools(res.schools || []);
    } catch (_) {
      setSchools([]);
    }
  };

  useEffect(() => {
    loadPermissions();
    loadSchools();
  }, [userId]);

  const handleAdd = async () => {
    if (!schoolId) {
      setError('Select a school.');
      return;
    }
    setAdding(true);
    setError('');
    try {
      await API.addPermission(userId, { school_id: parseInt(schoolId, 10) });
      await loadPermissions();
      setSchoolId('');
    } catch (err) {
      setError(err.message);
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (perm) => {
    if (!window.confirm(`Remove access to ${perm.school_name}? (This removes access to all seasons for that school.)`)) return;
    setRemoving(perm.id);
    try {
      await API.removePermission(userId, perm.id);
      await loadPermissions();
    } catch (err) {
      setError(err.message);
    } finally {
      setRemoving(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>Loading...</div>
    );
  }

  const userName = targetUser
    ? `${(targetUser.first_name || '').trim()} ${(targetUser.last_name || '').trim()}`.trim() || targetUser.display_name || targetUser.username
    : 'User';

  return (
    <Layout user={user}>
      {error && <div className="alert alert-danger" style={{ marginBottom: 14 }}>{error}</div>}
      <nav className="MuiTypography-root MuiBreadcrumbs-root jss74 MuiTypography-body1 MuiTypography-colorTextSecondary" aria-label="breadcrumb">
        <ol className="MuiBreadcrumbs-ol" style={{ listStyle: 'none', display: 'flex', padding: 0, margin: 0, flexWrap: 'wrap', alignItems: 'center' }}>
          <li className="MuiBreadcrumbs-li"><span>Accounts</span></li>
          <li aria-hidden="true" className="MuiBreadcrumbs-separator">›</li>
          <li className="MuiBreadcrumbs-li">
            <Link to="/manage-users" style={{ color: '#D10B0B', textDecoration: 'none' }}>Users</Link>
          </li>
          <li aria-hidden="true" className="MuiBreadcrumbs-separator">›</li>
          <li className="MuiBreadcrumbs-li"><span>RPI Access</span></li>
        </ol>
      </nav>
      <div className="MuiBox-root jss166 jss75">
        <div className="MuiBox-root jss167">
          <p className="MuiTypography-root jss135 MuiTypography-body1">
            RPI Access – {userName}
          </p>
        </div>
        <p className="MuiTypography-root MuiTypography-body2" style={{ color: '#767676', fontSize: 14, marginTop: 4 }}>
          Assign a school to grant access to all seasons for that school, including future seasons.
        </p>
      </div>
      <div className="MuiPaper-root jss71 jss72 jss76 MuiPaper-elevation3 MuiPaper-rounded" style={{ marginTop: 16 }}>
        <div className="MuiBox-root jss81 jss73">
          <div className="MuiBox-root jss82 jss65" style={{ padding: 16 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginBottom: 16 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, color: '#767676', marginBottom: 4 }}>School</label>
                <select
                  className="MuiSelect-select"
                  value={schoolId}
                  onChange={(e) => setSchoolId(e.target.value)}
                  style={{
                    padding: '8px 12px',
                    border: '1px solid rgba(0,0,0,0.23)',
                    borderRadius: 4,
                    fontSize: 14,
                    minWidth: 200,
                  }}
                >
                  <option value="">Select school</option>
                  {schools
                    .filter((s) => !permissions.some((p) => p.school_id === s.id))
                    .map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                </select>
              </div>
              <button
                type="button"
                className="MuiButtonBase-root MuiButton-root MuiButton-contained MuiButton-containedPrimary"
                disabled={adding || !schoolId}
                onClick={handleAdd}
                style={{
                  padding: '8px 22px',
                  backgroundColor: '#D10B0B',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: adding || !schoolId ? 'not-allowed' : 'pointer',
                  opacity: adding || !schoolId ? 0.7 : 1,
                }}
              >
                {adding ? 'Adding...' : 'Add Access'}
              </button>
            </div>
            <div className="MuiPaper-root jss87 MuiPaper-outlined MuiPaper-rounded">
              <div className="MuiTableContainer-root jss88">
                <table className="MuiTable-root MuiTable-stickyHeader table" aria-label="permissions">
                  <thead className="MuiTableHead-root">
                    <tr className="MuiTableRow-root jss90 MuiTableRow-head">
                      <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignLeft" scope="col">SCHOOL</th>
                      <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignRight" scope="col" style={{ width: 100 }} />
                    </tr>
                  </thead>
                  <tbody className="MuiTableBody-root">
                    {permissions.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="MuiTableCell-root MuiTableCell-body" style={{ textAlign: 'center', padding: 24 }}>
                          No school access yet. Assign a school above to grant access to all seasons (current and future).
                        </td>
                      </tr>
                    ) : (
                      permissions.map((p) => (
                        <tr key={p.id} className="MuiTableRow-root MuiTableRow-hover">
                          <td className="MuiTableCell-root MuiTableCell-body">{p.school_name}</td>
                          <td className="MuiTableCell-root MuiTableCell-body MuiTableCell-alignRight">
                            <button
                              type="button"
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#BA1A1A',
                                cursor: removing === p.id ? 'not-allowed' : 'pointer',
                                fontSize: 14,
                              }}
                              disabled={removing === p.id}
                              onClick={() => handleRemove(p)}
                            >
                              {removing === p.id ? 'Removing...' : 'Remove'}
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
      <p style={{ marginTop: 16 }}>
        <Link to="/manage-users" style={{ color: '#D10B0B', textDecoration: 'none' }}>← Back to Users</Link>
      </p>
    </Layout>
  );
}
