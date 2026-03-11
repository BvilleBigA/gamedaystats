const API = {
  base: '',
  async fetch(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const headers = {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    };
    const res = await fetch(`${this.base}${path}`, {
      ...options,
      credentials: 'include',
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || res.statusText);
    }
    return res.json();
  },
  getMe() {
    return this.fetch('/api/admin/me');
  },
  getUsers() {
    return this.fetch('/api/admin/users');
  },
  addUser(data) {
    return this.fetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteUser(id) {
    return this.fetch(`/api/admin/users/${id}`, { method: 'DELETE' });
  },
  getPermissions(userId) {
    return this.fetch(`/api/admin/users/${userId}/permissions`);
  },
  addPermission(userId, { school_id }) {
    return this.fetch(`/api/admin/users/${userId}/permissions`, {
      method: 'POST',
      body: JSON.stringify({ school_id }),
    });
  },
  removePermission(userId, permId) {
    return this.fetch(`/api/admin/users/${userId}/permissions/${permId}`, {
      method: 'DELETE',
    });
  },
  getSchools() {
    return this.fetch('/api/admin/schools');
  },
  addSchool(data) {
    return this.fetch('/api/admin/schools', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteSchool(id) {
    return this.fetch(`/api/admin/schools/${id}`, { method: 'DELETE' });
  },
  updateSchool(id, data) {
    return this.fetch(`/api/admin/schools/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },
  uploadSchoolLogo(schoolId, file) {
    const formData = new FormData();
    formData.append('logo', file);
    return this.fetch(`/api/admin/schools/${schoolId}/logo`, {
      method: 'POST',
      body: formData,
    });
  },
  getDatabaseData() {
    return this.fetch('/api/admin/schools');
  },
  getSeasons() {
    return this.fetch('/api/admin/database/seasons');
  },
  getSeasonTeams(seasonId) {
    return this.fetch(`/api/admin/seasons/${seasonId}/teams`);
  },
  addSchoolToSeason(schoolId, data) {
    return this.fetch(`/api/admin/schools/${schoolId}/add-to-season`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteTeam(teamId) {
    return this.fetch(`/api/admin/teams/${teamId}`, { method: 'DELETE' });
  },
  addSeason(data) {
    return this.fetch('/api/admin/seasons', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
  deleteSeason(id) {
    return this.fetch(`/api/admin/seasons/${id}`, { method: 'DELETE' });
  },
};

export default API;
