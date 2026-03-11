import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import API from '../api';

export default function UsersTable({ users, currentUserId, onRefresh }) {
  const [search, setSearch] = useState('');
  const [openMenuId, setOpenMenuId] = useState(null);
  const [deleting, setDeleting] = useState(null);

  useEffect(() => {
    const close = () => setOpenMenuId(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);

  const filtered = users.filter((u) => {
    const q = search.toLowerCase();
    const s = `${u.first_name || ''} ${u.last_name || ''} ${u.username || ''} ${u.phone || ''}`.toLowerCase();
    return !q || s.includes(q);
  });

  const handleDelete = async (u) => {
    if (!window.confirm('Permanently delete this user?')) return;
    setDeleting(u.id);
    try {
      await API.deleteUser(u.id);
      onRefresh?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setDeleting(null);
      setOpenMenuId(null);
    }
  };

  return (
    <div className="MuiPaper-root jss71 jss72 jss76 MuiPaper-elevation3 MuiPaper-rounded">
      <div className="MuiBox-root jss81 jss73">
        <div className="MuiBox-root jss82 jss65">
          <div className="MuiGrid-root jss68 MuiGrid-container MuiGrid-align-items-xs-center MuiGrid-justify-xs-space-between">
            <div className="MuiGrid-root MuiGrid-item">
              <div className="MuiFormControl-root MuiTextField-root jss69">
                <div className="MuiInputBase-root MuiOutlinedInput-root MuiInputBase-formControl MuiInputBase-marginDense MuiOutlinedInput-marginDense">
                  <input
                    placeholder="Search users"
                    type="text"
                    className="MuiInputBase-input MuiOutlinedInput-input MuiInputBase-inputMarginDense MuiOutlinedInput-inputMarginDense"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <fieldset aria-hidden="true" className="jss83 MuiOutlinedInput-notchedOutline" style={{ paddingLeft: 8 }}>
                    <legend className="jss84" style={{ width: '0.01px' }}><span>&#8203;</span></legend>
                  </fieldset>
                </div>
              </div>
            </div>
            <div className="MuiGrid-root MuiGrid-item">
              <span className="MuiTypography-root MuiTypography-caption">* Indicates account administrator.</span>
            </div>
          </div>
          <div className="MuiPaper-root jss87 MuiPaper-outlined MuiPaper-rounded">
            <div className="MuiTableContainer-root jss88">
              <table className="MuiTable-root MuiTable-stickyHeader table" aria-label="sticky table">
                <thead className="MuiTableHead-root">
                  <tr className="MuiTableRow-root jss90 MuiTableRow-head">
                    <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignLeft MuiTableCell-stickyHeader" scope="col">FIRST NAME</th>
                    <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignLeft MuiTableCell-stickyHeader" scope="col">LAST NAME</th>
                    <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignLeft MuiTableCell-stickyHeader" scope="col">EMAIL ADDRESS</th>
                    <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignLeft MuiTableCell-stickyHeader" scope="col">PHONE NUMBER</th>
                    <th className="MuiTableCell-root MuiTableCell-head MuiTableCell-alignRight MuiTableCell-stickyHeader" scope="col" style={{ padding: 0 }} />
                  </tr>
                </thead>
                <tbody className="MuiTableBody-root">
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="MuiTableCell-root MuiTableCell-body" style={{ textAlign: 'center', padding: 24 }}>
                        No users yet.
                      </td>
                    </tr>
                  ) : (
                    filtered.map((u) => (
                      <tr
                        key={u.id}
                        className="MuiTableRow-root MuiTableRow-hover"
                        role="checkbox"
                        tabIndex={-1}
                      >
                        <td className="MuiTableCell-root MuiTableCell-body jss66">
                          <span>{u.first_name || '—'}</span>
                        </td>
                        <td className="MuiTableCell-root MuiTableCell-body jss67">
                          <span>{u.last_name || '—'}</span>
                        </td>
                        <td className="MuiTableCell-root MuiTableCell-body">
                          <span>{u.username}{u.role === 'admin' ? ' (*)' : ''}</span>
                        </td>
                        <td className="MuiTableCell-root MuiTableCell-body">
                          <span>{u.phone || ''}</span>
                        </td>
                        <td className="MuiTableCell-root MuiTableCell-body MuiTableCell-alignRight">
                          <div className="dropdown" style={{ position: 'relative' }}>
                            <button
                              type="button"
                              className="MuiButtonBase-root MuiIconButton-root MuiIconButton-sizeSmall"
                              onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpenMenuId(openMenuId === u.id ? null : u.id); }}
                              aria-label="more actions"
                            >
                              <span className="MuiIconButton-label">
                                <svg className="MuiSvgIcon-root" focusable="false" viewBox="0 0 32 32" aria-hidden="true">
                                  <circle cx="16" cy="8" r="2" />
                                  <circle cx="16" cy="16" r="2" />
                                  <circle cx="16" cy="24" r="2" />
                                </svg>
                              </span>
                            </button>
                            {openMenuId === u.id && (
                              <ul
                                className="dropdown-menu dropdown-menu-right"
                                role="menu"
                                style={{
                                  position: 'absolute',
                                  right: 0,
                                  top: '100%',
                                  display: 'block',
                                  marginTop: 4,
                                  minWidth: 204,
                                }}
                              >
                                <li>
                                  <a href={u.id === currentUserId ? '/admin/user' : `/admin/user`} role="menuitem">
                                    Edit profile
                                  </a>
                                </li>
                                <li>
                                  <Link to={`/manage-users/permissions/${u.id}`} role="menuitem" style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none' }}>
                                    RPI Access
                                  </Link>
                                </li>
                                {u.id !== currentUserId && (
                                  <>
                                    <li role="separator" className="divider" />
                                    <li>
                                      <button
                                        type="button"
                                        className="jss146"
                                        style={{
                                          background: 'none',
                                          border: 'none',
                                          width: '100%',
                                          textAlign: 'left',
                                          padding: '8px 16px',
                                          cursor: 'pointer',
                                          color: '#BA1A1A',
                                        }}
                                        disabled={deleting === u.id}
                                        onClick={() => handleDelete(u)}
                                      >
                                        {deleting === u.id ? 'Removing...' : 'Remove User'}
                                      </button>
                                    </li>
                                  </>
                                )}
                              </ul>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <hr className="MuiDivider-root" />
            <div className="MuiTablePagination-root jss91">
              <div className="MuiToolbar-root MuiToolbar-regular MuiTablePagination-toolbar MuiToolbar-gutters">
                <div className="MuiTablePagination-spacer" />
                <p className="MuiTypography-root MuiTablePagination-caption MuiTypography-body2 MuiTypography-colorInherit">
                  {filtered.length > 0 ? `1-${filtered.length} of ${filtered.length}` : '0-0 of 0'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
