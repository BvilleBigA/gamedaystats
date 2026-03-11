import { useState, useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import Layout from './Layout';
import API from '../api';

const SPORT_GROUPS = [
  ['Baseball', ['bsb', 'hsvarsitybsb', 'hsjvbsb']],
  ['Softball', ['sb', 'sballhs', 'hsvarsitysb', 'hsjvsb']],
  ['Boys Basketball', ['mbkb', 'hsvarsitymbkb', 'hsjvmbkb']],
  ['Girls Basketball', ['wbkb', 'hsvarsitywbkb', 'hsjvwbkb']],
  ['Football', ['fb', 'hsvarsityfb', 'hsjvfb']],
  ['Boys Soccer', ['msoc', 'hsvarsitymsoc', 'hsjvmsoc']],
  ['Girls Soccer', ['wsoc', 'hsvarsitywsoc', 'hsjvwsoc']],
  ['Volleyball', ['vb', 'hsvarsityvb', 'hsjvvb']],
  ['Ice Hockey', ['ih', 'mih', 'wih']],
  ["Men's Lacrosse", ['mlax', 'hsvarsitymlax']],
  ["Women's Lacrosse", ['wlax', 'hsvarsitywlax']],
  ['Tennis', ['ten', 'mten', 'wten']],
  ['Field Hockey', ['fh', 'hsvarsityfh']],
  ['Water Polo', ['wp', 'mwp', 'wwp']],
];

const SPORT_NAMES = {
  bsb: 'Baseball', hsvarsitybsb: 'HS Varsity Baseball', hsjvbsb: 'HS JV Baseball',
  sb: 'Softball', sballhs: 'Girls Softball', hsvarsitysb: 'HS Varsity Softball', hsjvsb: 'HS JV Softball',
  mbkb: 'Boys Basketball', hsvarsitymbkb: 'HS Varsity Boys Basketball', hsjvmbkb: 'HS JV Boys Basketball',
  wbkb: 'Girls Basketball', hsvarsitywbkb: 'HS Varsity Girls Basketball', hsjvwbkb: 'HS JV Girls Basketball',
  fb: 'Football', hsvarsityfb: 'HS Varsity Football', hsjvfb: 'HS JV Football',
  msoc: 'Boys Soccer', hsvarsitymsoc: 'HS Varsity Boys Soccer', hsjvmsoc: 'HS JV Boys Soccer',
  wsoc: 'Girls Soccer', hsvarsitywsoc: 'HS Varsity Girls Soccer', hsjvwsoc: 'HS JV Girls Soccer',
  vb: 'Volleyball', hsvarsityvb: 'HS Varsity Volleyball', hsjvvb: 'HS JV Volleyball',
  ih: 'Ice Hockey', mih: "Men's Ice Hockey", wih: "Women's Ice Hockey",
  mlax: "Men's Lacrosse", hsvarsitymlax: 'HS Varsity Boys Lacrosse',
  wlax: "Women's Lacrosse", hsvarsitywlax: 'HS Varsity Girls Lacrosse',
  ten: 'Tennis', mten: "Men's Tennis", wten: "Women's Tennis",
  fh: 'Field Hockey', hsvarsityfh: 'HS Varsity Field Hockey',
  wp: 'Water Polo', mwp: "Men's Water Polo", wwp: "Women's Water Polo",
};

function prettyDate(s) {
  if (!s || !s.trim()) return '—';
  const m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}/${m[1]}`;
  return s;
}

const inputStyle = {
  padding: '8px 12px',
  border: '1px solid rgba(0,0,0,0.23)',
  borderRadius: 4,
  fontSize: 14,
  boxSizing: 'border-box',
  width: '100%',
  maxWidth: 280,
};
const btnPrimary = { padding: '8px 22px', backgroundColor: '#D10B0B', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' };
const btnDel = { ...btnPrimary, backgroundColor: 'transparent', color: '#BA1A1A' };

function SchoolKebabMenu({ sc, open, onToggle, onEditSchool, onAddToSeason, onDelete, onClose }) {
  const btnRef = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
    } else {
      setPos(null);
    }
  }, [open]);
  const menuStyle = pos ? { position: 'fixed', top: pos.top, right: pos.right, minWidth: 160, zIndex: 1301, backgroundColor: '#fff', listStyle: 'none', margin: 0, padding: 0, boxShadow: '0 4px 12px rgba(0,0,0,.2)', borderRadius: 4, display: 'block' } : {};
  const overlayStyle = { position: 'fixed', inset: 0, zIndex: 1300, background: 'transparent' };
  return (
    <div style={{ display: 'inline-block', position: 'relative', marginRight: 8 }}>
      <button
        ref={btnRef}
        type="button"
        className="MuiButtonBase-root MuiIconButton-root MuiIconButton-sizeSmall"
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        aria-label="school actions"
      >
        <span className="MuiIconButton-label">
          <svg className="MuiSvgIcon-root" focusable="false" viewBox="0 0 32 32" style={{ width: 20, height: 20 }}>
            <circle cx="16" cy="8" r="2" /><circle cx="16" cy="16" r="2" /><circle cx="16" cy="24" r="2" />
          </svg>
        </span>
      </button>
      {open && pos && createPortal(
        <>
          <div style={overlayStyle} onClick={onClose} aria-hidden="true" />
          <ul className="dropdown-menu dropdown-menu-right" role="menu" style={menuStyle}>
            <li><button type="button" style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px 16px', cursor: 'pointer' }} onClick={onEditSchool}>Edit school</button></li>
            <li><button type="button" style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px 16px', cursor: 'pointer' }} onClick={onAddToSeason}>Add to season</button></li>
            <li><button type="button" style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px 16px', cursor: 'pointer', color: '#BA1A1A' }} onClick={onDelete}>Delete</button></li>
          </ul>
        </>,
        document.body
      )}
    </div>
  );
}

function SeasonKebabMenu({ s, open, onToggle, onEditTeams, onClose }) {
  const btnRef = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
    } else {
      setPos(null);
    }
  }, [open]);
  const menuStyle = pos ? { position: 'fixed', top: pos.top, right: pos.right, minWidth: 160, zIndex: 1301, backgroundColor: '#fff', listStyle: 'none', margin: 0, padding: 0, boxShadow: '0 4px 12px rgba(0,0,0,.2)', borderRadius: 4, display: 'block' } : {};
  const overlayStyle = { position: 'fixed', inset: 0, zIndex: 1300, background: 'transparent' };
  return (
    <div style={{ display: 'inline-block', position: 'relative', marginRight: 8 }}>
      <button
        ref={btnRef}
        type="button"
        className="MuiButtonBase-root MuiIconButton-root MuiIconButton-sizeSmall"
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        aria-label="more actions"
      >
        <span className="MuiIconButton-label">
          <svg className="MuiSvgIcon-root" focusable="false" viewBox="0 0 32 32" style={{ width: 20, height: 20 }}>
            <circle cx="16" cy="8" r="2" /><circle cx="16" cy="16" r="2" /><circle cx="16" cy="24" r="2" />
          </svg>
        </span>
      </button>
      {open && pos && createPortal(
        <>
          <div style={overlayStyle} onClick={onClose} aria-hidden="true" />
          <ul className="dropdown-menu dropdown-menu-right" role="menu" style={menuStyle}>
            <li><button type="button" style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', padding: '8px 16px', cursor: 'pointer' }} onClick={onEditTeams}>Edit teams</button></li>
          </ul>
        </>,
        document.body
      )}
    </div>
  );
}

function SchoolModal({ school, open, onClose, onSuccess }) {
  const isEdit = !!school;
  const [form, setForm] = useState({
    school_name: '', rpi: '', code: '', city: '', state: '',
  });
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) {
      if (school) {
        setForm({
          school_name: school.name || '',
          rpi: school.rpi || '',
          code: school.code || '',
          city: school.city || '',
          state: school.state || '',
        });
      } else {
        setForm({ school_name: '', rpi: '', code: '', city: '', state: '' });
      }
      setFile(null);
      setPreview('');
      setErr('');
    }
  }, [open, school?.id]);

  const handleFileChange = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const ok = /\.(png|jpe?g|gif|webp|svg)$/i.test(f.name);
    if (!ok) {
      setErr('Use PNG, JPG, GIF, WebP, or SVG');
      setFile(null);
      setPreview('');
      return;
    }
    setErr('');
    setFile(f);
    const r = new FileReader();
    r.onload = () => setPreview(r.result);
    r.readAsDataURL(f);
  };

  const handleSaveSchool = async (e) => {
    e.preventDefault();
    const name = (form.school_name || '').trim();
    if (!name) {
      setErr('School name is required.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      if (isEdit) {
        await API.updateSchool(school.id, {
          school_name: name, rpi: form.rpi, code: form.code, city: form.city, state: form.state,
        });
        onClose();
        onSuccess?.();
      } else {
        const res = await API.addSchool(form);
        if (file && res?.school?.id) {
          await API.uploadSchoolLogo(res.school.id, file);
        }
        onClose();
        onSuccess?.();
      }
    } catch (e) {
      setErr(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleUploadLogo = async (e) => {
    e.preventDefault();
    if (!school || !file) return;
    setUploading(true);
    setErr('');
    try {
      await API.uploadSchoolLogo(school.id, file);
      setFile(null);
      setPreview('');
      onSuccess?.();
    } catch (e) {
      setErr(e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleClose = () => {
    setFile(null);
    setPreview('');
    setErr('');
    onClose();
  };

  if (!open) return null;
  return (
    <div style={{ position: 'fixed', zIndex: 1300, inset: 0 }}>
      <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', cursor: 'pointer' }} onClick={handleClose} aria-hidden="true" />
      <div style={{ position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1301, pointerEvents: 'none' }}>
        <div style={{ backgroundColor: '#fff', borderRadius: 8, maxWidth: 440, width: '100%', margin: 24, boxShadow: '0 11px 15px -7px rgba(0,0,0,0.2)', pointerEvents: 'auto', maxHeight: '90vh', overflow: 'auto' }} onClick={(e) => e.stopPropagation()}>
          <div style={{ padding: 16, borderBottom: '1px solid #eee', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: 18 }}>{isEdit ? `Edit school — ${school?.name}` : 'Add school'}</h3>
            <button type="button" aria-label="close" onClick={handleClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>✕</button>
          </div>
          <div style={{ padding: 16 }}>
            {err && <div style={{ color: '#c00', marginBottom: 12, fontSize: 13 }}>{err}</div>}
            <form onSubmit={handleSaveSchool} style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
                <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>School name *</label><input value={form.school_name} onChange={(e) => setForm({ ...form, school_name: e.target.value })} required style={inputStyle} placeholder="e.g. Springfield High" /></div>
                <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>RPI</label><input value={form.rpi} onChange={(e) => setForm({ ...form, rpi: e.target.value })} style={{ ...inputStyle, maxWidth: 80 }} placeholder="127" /></div>
                <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Code</label><input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} style={{ ...inputStyle, maxWidth: 80 }} placeholder="SPH" maxLength={8} /></div>
                <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>City</label><input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} style={inputStyle} /></div>
                <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>State</label><input value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })} style={{ ...inputStyle, maxWidth: 60 }} maxLength={4} /></div>
                <button type="submit" style={btnPrimary} disabled={saving}>{saving ? 'Saving…' : isEdit ? 'Save' : 'Add'}</button>
              </div>
            </form>

            <div style={{ borderTop: '1px solid #eee', paddingTop: 16, marginTop: 16 }}>
              <h4 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 600 }}>School logo</h4>
              <form onSubmit={handleUploadLogo} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Choose image (PNG, JPG, GIF, WebP, SVG)</label>
                  <input type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.svg" onChange={handleFileChange} style={{ fontSize: 13 }} />
                </div>
                {preview && (
                  <div>
                    <img src={preview} alt="Preview" style={{ maxWidth: 120, maxHeight: 80, objectFit: 'contain', border: '1px solid #ddd', borderRadius: 4 }} />
                  </div>
                )}
                <button type="submit" style={{ ...btnPrimary, alignSelf: 'flex-start' }} disabled={!file || uploading || !school}>{uploading ? 'Uploading…' : 'Upload logo'}</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function EditTeamsModal({ season, schools, open, onClose, onSuccess }) {
  const [teams, setTeams] = useState([]);
  const [loading, setLoading] = useState(false);
  const [addSchoolId, setAddSchoolId] = useState('');
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState(null);

  useEffect(() => {
    if (open && season) {
      setLoading(true);
      API.getSeasonTeams(season.id).then((res) => {
        setTeams(res.teams || []);
        setLoading(false);
      }).catch(() => setLoading(false));
    }
  }, [open, season?.id]);

  const handleAddSchool = async (e) => {
    e.preventDefault();
    if (!addSchoolId) return;
    setAdding(true);
    try {
      await API.addSchoolToSeason(parseInt(addSchoolId, 10), { existing_season_id: String(season.id) });
      const res = await API.getSeasonTeams(season.id);
      setTeams(res.teams || []);
      setAddSchoolId('');
      onSuccess?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setAdding(false);
    }
  };

  const handleDeleteTeam = async (team) => {
    if (!window.confirm(`Remove ${team.name} from this season?`)) return;
    setDeleting(team.id);
    try {
      await API.deleteTeam(team.id);
      setTeams((prev) => prev.filter((t) => t.id !== team.id));
      onSuccess?.();
    } catch (err) {
      alert(err.message);
    } finally {
      setDeleting(null);
    }
  };

  if (!open) return null;
  const schoolsNotInSeason = (schools || []).filter((sc) => !teams.some((t) => t.school_name === sc.name));

  return (
    <div style={{ position: 'fixed', zIndex: 1300, inset: 0 }}>
      <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', cursor: 'pointer' }} onClick={onClose} aria-hidden="true" />
      <div style={{ position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1301, pointerEvents: 'none' }}>
        <div style={{ backgroundColor: '#fff', borderRadius: 8, maxWidth: 480, width: '100%', margin: 24, boxShadow: '0 11px 15px -7px rgba(0,0,0,0.2)', pointerEvents: 'auto', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }} onClick={(e) => e.stopPropagation()}>
          <div style={{ padding: 16, borderBottom: '1px solid #eee', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: 18 }}>Edit teams — {season?.name}</h3>
            <button type="button" aria-label="close" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>✕</button>
          </div>
          <div style={{ padding: 16, flex: 1, overflow: 'auto' }}>
            <form onSubmit={handleAddSchool} style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 160 }}>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Add school</label>
                <select value={addSchoolId} onChange={(e) => setAddSchoolId(e.target.value)} style={inputStyle} disabled={schoolsNotInSeason.length === 0}>
                  <option value="">Select school</option>
                  {schoolsNotInSeason.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <button type="submit" style={btnPrimary} disabled={!addSchoolId || adding}>{adding ? 'Adding...' : 'Add'}</button>
            </form>
            {loading ? (
              <p style={{ color: '#999' }}>Loading teams...</p>
            ) : teams.length === 0 ? (
              <p style={{ color: '#999', fontStyle: 'italic' }}>No teams yet. Add a school above.</p>
            ) : (
              <table className="MuiTable-root table" style={{ width: '100%' }}>
                <thead><tr className="MuiTableRow-head"><th>Team</th><th>Code</th><th style={{ width: 80 }}></th></tr></thead>
                <tbody>
                  {teams.map((t) => (
                    <tr key={t.id}>
                      <td>{t.name}</td>
                      <td>{t.code || '—'}</td>
                      <td>
                        <button type="button" style={{ ...btnDel, padding: '4px 8px', fontSize: 12 }} disabled={deleting === t.id} onClick={() => handleDeleteTeam(t)}>
                          {deleting === t.id ? '…' : 'Remove'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ManageDatabase() {
  const [activeTab, setActiveTab] = useState('schools');
  const [user, setUser] = useState(null);
  const [schools, setSchools] = useState([]);
  const [seasons, setSeasons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [addSeasonOpen, setAddSeasonOpen] = useState(false);
  const [addToSeasonSchoolId, setAddToSeasonSchoolId] = useState(null);
  const [seasonForm, setSeasonForm] = useState({ season_name: '', sport_code: 'bsb', gender: 'male', start_date: '', end_date: '' });
  const [addToSeasonForm, setAddToSeasonForm] = useState({ existing_season_id: '', new_season_name: '', sport_code: 'bsb', gender: 'female' });
  const [openMenuSeasonId, setOpenMenuSeasonId] = useState(null);
  const [editTeamsSeason, setEditTeamsSeason] = useState(null);
  const [openMenuSchoolId, setOpenMenuSchoolId] = useState(null);
  const [schoolModalSchool, setSchoolModalSchool] = useState(undefined);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const [meRes, schoolsRes, seasonsRes] = await Promise.all([
        API.getMe(),
        API.getDatabaseData(),
        API.getSeasons(),
      ]);
      setUser(meRes.user);
      setSchools(schoolsRes.schools || []);
      setSeasons(seasonsRes.seasons || []);
      if (seasonsRes.sport_codes) Object.assign(SPORT_NAMES, seasonsRes.sport_codes);
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

  useEffect(() => { loadData(); }, []);

  const closeMenus = () => {
    setOpenMenuSeasonId(null);
    setOpenMenuSchoolId(null);
  };

  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(''), 4000);
      return () => clearTimeout(t);
    }
  }, [success]);

  const handleDeleteSchool = async (sc) => {
    if (!window.confirm(`Delete school "${sc.name}"?`)) return;
    setError('');
    try {
      await API.deleteSchool(sc.id);
      setSuccess(`School "${sc.name}" deleted.`);
      loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleAddSeason = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await API.addSeason(seasonForm);
      setSuccess(`Season "${seasonForm.season_name}" created.`);
      setSeasonForm({ season_name: '', sport_code: 'bsb', gender: 'male', start_date: '', end_date: '' });
      setAddSeasonOpen(false);
      loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDeleteSeason = async (s) => {
    if (!window.confirm(`Delete season "${s.name}"? This will also delete all teams, games, and stats.`)) return;
    setError('');
    try {
      await API.deleteSeason(s.id);
      setSuccess(`Season "${s.name}" and all its data deleted.`);
      loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleAddSchoolToSeason = async (e) => {
    e.preventDefault();
    if (!addToSeasonSchoolId) return;
    setError('');
    try {
      await API.addSchoolToSeason(addToSeasonSchoolId, addToSeasonForm);
      setSuccess('Team added to season.');
      setAddToSeasonSchoolId(null);
      setAddToSeasonForm({ existing_season_id: '', new_season_name: '', sport_code: 'bsb', gender: 'female' });
      loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDeleteTeam = async (team, schoolName) => {
    if (!window.confirm(`Remove ${schoolName} from ${team.season_name}?`)) return;
    setError('');
    try {
      await API.deleteTeam(team.id);
      setSuccess(`Removed from season.`);
      loadData();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) return <div style={{ padding: 24, textAlign: 'center' }}>Loading...</div>;

  const sidebarStyle = {
    width: 220,
    flexShrink: 0,
    borderRight: '1px solid #E8E8E8',
    backgroundColor: '#fafafa',
    padding: '16px 0',
  };
  const tabStyle = (active) => ({
    display: 'block',
    width: '100%',
    padding: '12px 20px',
    border: 'none',
    background: 'none',
    cursor: 'pointer',
    textAlign: 'left',
    fontSize: 14,
    fontFamily: 'inherit',
    color: active ? '#D10B0B' : '#333',
    fontWeight: active ? 600 : 400,
  });

  return (
    <Layout user={user}>
      {error && <div className="alert alert-danger" style={{ marginBottom: 14 }}>{error}</div>}
      {success && <div className="alert alert-success" style={{ marginBottom: 14, backgroundColor: '#d4edda', color: '#155724', border: '1px solid #c3e6cb', borderRadius: 4, padding: '9px 14px' }}>{success}</div>}
      <nav className="MuiTypography-root MuiBreadcrumbs-root jss74 MuiTypography-body1 MuiTypography-colorTextSecondary" aria-label="breadcrumb">
        <ol className="MuiBreadcrumbs-ol" style={{ listStyle: 'none', display: 'flex', padding: 0, margin: 0, flexWrap: 'wrap', alignItems: 'center' }}>
          <li className="MuiBreadcrumbs-li"><span>Accounts</span></li>
          <li aria-hidden="true" className="MuiBreadcrumbs-separator">›</li>
          <li className="MuiBreadcrumbs-li"><Link to="/manage-users" style={{ color: '#D10B0B', textDecoration: 'none' }}>Users</Link></li>
          <li aria-hidden="true" className="MuiBreadcrumbs-separator">›</li>
          <li className="MuiBreadcrumbs-li"><span>Manage Database</span></li>
        </ol>
      </nav>
      <div className="MuiBox-root jss166 jss75" style={{ marginBottom: 16 }}>
        <p className="MuiTypography-root jss135 MuiTypography-body1">Schools, seasons, and RPI.</p>
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden', marginTop: 16 }}>
        <aside style={sidebarStyle}>
          <button type="button" style={tabStyle(activeTab === 'schools')} onClick={() => setActiveTab('schools')}>Manage Schools</button>
          <button type="button" style={tabStyle(activeTab === 'seasons')} onClick={() => setActiveTab('seasons')}>Manage Seasons</button>
        </aside>

        <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {activeTab === 'schools' && (
            <div className="MuiPaper-root jss71 jss72 jss76 MuiPaper-elevation3 MuiPaper-rounded" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <div style={{ padding: 16, flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ margin: '0 0 16px', fontSize: 18 }}>Schools</h2>
                <button type="button" style={{ ...btnPrimary, alignSelf: 'flex-start' }} onClick={() => setSchoolModalSchool(null)}>Add School</button>
                {schools.length === 0 ? (
                  <p style={{ color: '#999', fontStyle: 'italic', fontSize: 13 }}>No schools added yet.</p>
                ) : (
                  <div className="MuiPaper-root jss87 MuiPaper-outlined MuiPaper-rounded" style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
                    <table className="MuiTable-root table" style={{ minWidth: 500 }}>
                      <thead><tr className="MuiTableRow-head"><th>School</th><th>RPI</th><th>Code</th><th>City / State</th><th>Seasons</th><th></th></tr></thead>
                      <tbody>
                        {schools.map((sc) => (
                          <tr key={sc.id}>
                            <td><strong>{sc.name}</strong></td>
                            <td>{sc.rpi || '—'}</td>
                            <td>{sc.code || '—'}</td>
                            <td>{[sc.city, sc.state].filter(Boolean).join(', ') || '—'}</td>
                            <td>
                              {(sc.teams || []).map((t) => (
                                <span key={t.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                                  {t.season_name || '—'}
                                  <button type="button" style={{ ...btnDel, padding: '2px 6px', fontSize: 11 }} onClick={() => handleDeleteTeam(t, sc.name)}>✕</button>
                                </span>
                              ))}
                              {(!sc.teams || sc.teams.length === 0) && <em style={{ color: '#999', fontSize: 12 }}>None</em>}
                            </td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                              {addToSeasonSchoolId === sc.id ? (
                                <form onSubmit={handleAddSchoolToSeason} style={{ display: 'inline-block', background: '#fff', border: '1px solid #ccc', borderRadius: 4, padding: 12, minWidth: 280, boxShadow: '0 4px 12px rgba(0,0,0,.15)', marginBottom: 8 }} onClick={(e) => e.stopPropagation()}>
                                  <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Existing season</label>
                                  <select value={addToSeasonForm.existing_season_id} onChange={(e) => setAddToSeasonForm({ ...addToSeasonForm, existing_season_id: e.target.value })} style={inputStyle}>
                                    <option value="">— new season —</option>
                                    {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                                  </select>
                                  <label style={{ display: 'block', fontSize: 12, marginTop: 8, marginBottom: 4 }}>New season name</label>
                                  <input value={addToSeasonForm.new_season_name} onChange={(e) => setAddToSeasonForm({ ...addToSeasonForm, new_season_name: e.target.value })} style={inputStyle} placeholder="e.g. 2026 Varsity" />
                                  <label style={{ display: 'block', fontSize: 12, marginTop: 8, marginBottom: 4 }}>Sport</label>
                                  <select value={addToSeasonForm.sport_code} onChange={(e) => setAddToSeasonForm({ ...addToSeasonForm, sport_code: e.target.value })} style={inputStyle}>
                                    {SPORT_GROUPS.map(([groupName, codes]) => (
                                      <optgroup key={groupName} label={groupName}>
                                        {codes.map((c) => <option key={c} value={c}>{SPORT_NAMES[c] || c}</option>)}
                                      </optgroup>
                                    ))}
                                  </select>
                                  <label style={{ display: 'block', fontSize: 12, marginTop: 8, marginBottom: 4 }}>Gender</label>
                                  <select value={addToSeasonForm.gender} onChange={(e) => setAddToSeasonForm({ ...addToSeasonForm, gender: e.target.value })} style={inputStyle}>
                                    <option value="female">Female</option><option value="male">Male</option><option value="coed">Coed</option>
                                  </select>
                                  <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                                    <button type="submit" style={btnPrimary}>Add to Season</button>
                                    <button type="button" style={btnDel} onClick={() => setAddToSeasonSchoolId(null)}>Cancel</button>
                                  </div>
                                </form>
                              ) : (
                                <SchoolKebabMenu
                                  sc={sc}
                                  open={openMenuSchoolId === sc.id}
                                  onToggle={() => setOpenMenuSchoolId(openMenuSchoolId === sc.id ? null : sc.id)}
                                  onClose={closeMenus}
                                  onEditSchool={() => { setSchoolModalSchool(sc); setOpenMenuSchoolId(null); }}
                                  onAddToSeason={() => { setAddToSeasonSchoolId(sc.id); setOpenMenuSchoolId(null); }}
                                  onDelete={() => { handleDeleteSchool(sc); setOpenMenuSchoolId(null); }}
                                />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'seasons' && (
            <div className="MuiPaper-root jss71 jss72 jss76 MuiPaper-elevation3 MuiPaper-rounded" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <div style={{ padding: 16, flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ margin: '0 0 16px', fontSize: 18 }}>Seasons</h2>
                {!addSeasonOpen ? (
                  <button type="button" style={{ ...btnPrimary, alignSelf: 'flex-start' }} onClick={() => setAddSeasonOpen(true)}>Add Season</button>
                ) : (
                  <form onSubmit={handleAddSeason} style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginBottom: 16, alignSelf: 'flex-start' }}>
                    <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Season Name *</label><input value={seasonForm.season_name} onChange={(e) => setSeasonForm({ ...seasonForm, season_name: e.target.value })} required style={inputStyle} placeholder="e.g. 2026 Varsity Softball" /></div>
                    <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Sport</label>
                      <select value={seasonForm.sport_code} onChange={(e) => setSeasonForm({ ...seasonForm, sport_code: e.target.value })} style={inputStyle}>
                        {SPORT_GROUPS.map(([groupName, codes]) => (
                          <optgroup key={groupName} label={groupName}>
                            {codes.map((c) => <option key={c} value={c}>{SPORT_NAMES[c] || c}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </div>
                    <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Gender</label>
                      <select value={seasonForm.gender} onChange={(e) => setSeasonForm({ ...seasonForm, gender: e.target.value })} style={inputStyle}>
                        <option value="male">Male</option><option value="female">Female</option><option value="coed">Coed</option>
                      </select>
                    </div>
                    <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Start</label><input type="date" value={seasonForm.start_date} onChange={(e) => setSeasonForm({ ...seasonForm, start_date: e.target.value })} style={inputStyle} /></div>
                    <div><label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>End</label><input type="date" value={seasonForm.end_date} onChange={(e) => setSeasonForm({ ...seasonForm, end_date: e.target.value })} style={inputStyle} /></div>
                    <button type="submit" style={btnPrimary}>Add</button>
                    <button type="button" style={btnDel} onClick={() => setAddSeasonOpen(false)}>Cancel</button>
                  </form>
                )}
                {seasons.length > 0 && (
                  <div className="MuiPaper-root jss87 MuiPaper-outlined MuiPaper-rounded" style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
                    <table className="MuiTable-root table">
                      <thead><tr className="MuiTableRow-head"><th>Season</th><th>Sport</th><th>Gender</th><th>Start</th><th>End</th><th style={{ width: 120 }}></th></tr></thead>
                      <tbody>
                        {seasons.map((s) => (
                          <tr key={s.id}>
                            <td><strong>{s.name}</strong></td>
                            <td>{SPORT_NAMES[s.sport_code] || s.sport_code}</td>
                            <td>{s.gender}</td>
                            <td>{prettyDate(s.start_date)}</td>
                            <td>{prettyDate(s.end_date)}</td>
                            <td style={{ whiteSpace: 'nowrap' }}>
                              <SeasonKebabMenu
                                s={s}
                                open={openMenuSeasonId === s.id}
                                onToggle={() => setOpenMenuSeasonId(openMenuSeasonId === s.id ? null : s.id)}
                                onClose={closeMenus}
                                onEditTeams={() => { setEditTeamsSeason(s); setOpenMenuSeasonId(null); }}
                              />
                              <button type="button" style={btnDel} onClick={() => handleDeleteSeason(s)}>Delete</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <EditTeamsModal
        season={editTeamsSeason}
        schools={schools}
        open={!!editTeamsSeason}
        onClose={() => setEditTeamsSeason(null)}
        onSuccess={loadData}
      />
      <SchoolModal
        school={schoolModalSchool}
        open={schoolModalSchool !== undefined}
        onClose={() => setSchoolModalSchool(undefined)}
        onSuccess={() => { loadData(); setSuccess(schoolModalSchool ? 'School updated.' : 'School added.'); }}
      />
    </Layout>
  );
}
