import { useState } from 'react';
import API from '../api';

export default function AddUserModal({ open, onClose, onSuccess }) {
  const [email, setEmail] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setEmail('');
    setFirstName('');
    setLastName('');
    setPhone('');
    setPassword('');
    setError('');
  };

  const handleClose = () => {
    reset();
    onClose?.();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await API.addUser({
        email: email.trim(),
        password: password.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        phone: phone.trim(),
      });
      handleClose();
      onSuccess?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="MuiDialog-root add-user-dialog"
      style={{
        position: 'fixed',
        zIndex: 1300,
        inset: 0,
        visibility: 'visible',
      }}
    >
      <div
        className="MuiBackdrop-root"
        style={{
          opacity: 0.5,
          visibility: 'visible',
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          cursor: 'pointer',
          backgroundColor: 'rgba(0,0,0,0.5)',
        }}
        onClick={handleClose}
        aria-hidden="true"
      />
      <div
        className="MuiDialog-container MuiDialog-scrollPaper"
        role="presentation"
        tabIndex={-1}
        style={{
          opacity: 1,
          visibility: 'visible',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'fixed',
          inset: 0,
          zIndex: 1301,
        }}
      >
        <div
          className="MuiPaper-root MuiDialog-paper MuiDialog-paperScrollPaper MuiDialog-paperWidthSm MuiPaper-elevation24 MuiPaper-rounded add-user-modal"
          role="dialog"
          aria-labelledby="add-user-dialog-title"
          style={{
            backgroundColor: '#fff',
            borderRadius: 8,
            maxWidth: 400,
            width: '100%',
            margin: 24,
            position: 'relative',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="MuiButtonBase-root MuiIconButton-root jss103"
            aria-label="close"
            onClick={handleClose}
            style={{
              position: 'absolute',
              right: 8,
              top: 8,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            <span className="MuiIconButton-label">
              <svg className="MuiSvgIcon-root" focusable="false" viewBox="0 0 32 32">
                <path d="M24 9.4L22.6 8 16 14.6 9.4 8 8 9.4 14.6 16 8 22.6 9.4 24 16 17.4 22.6 24 24 22.6 17.4 16 24 9.4z" />
              </svg>
            </span>
          </button>
          <div className="MuiBox-root jss153" style={{ padding: 24 }}>
            <p className="MuiTypography-root jss135 MuiTypography-body1" id="add-user-dialog-title">
              Add User
            </p>
            <p className="MuiTypography-root jss102 MuiTypography-body1" style={{ marginBottom: 16 }}>
              Enter a password for the new user. You can share it with them separately.
            </p>
            {error && (
              <p style={{ color: '#BA1A1A', marginBottom: 16 }}>{error}</p>
            )}
            <form onSubmit={handleSubmit}>
              <div className="MuiGrid-root jss104 MuiGrid-container" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <label htmlFor="emailAddress" style={{ display: 'block', marginBottom: 4, fontSize: '0.875rem' }}>
                    Email
                  </label>
                  <input
                    id="emailAddress"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="add-user-input"
                  />
                </div>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <label htmlFor="firstName" style={{ display: 'block', marginBottom: 4, fontSize: '0.875rem' }}>
                    First Name
                  </label>
                  <input
                    id="firstName"
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    className="add-user-input"
                  />
                </div>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <label htmlFor="lastName" style={{ display: 'block', marginBottom: 4, fontSize: '0.875rem' }}>
                    Last Name
                  </label>
                  <input
                    id="lastName"
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    className="add-user-input"
                  />
                </div>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <label htmlFor="phoneNumber" style={{ display: 'block', marginBottom: 4, fontSize: '0.875rem' }}>
                    Phone
                  </label>
                  <input
                    id="phoneNumber"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="add-user-input"
                  />
                </div>
                <div style={{ width: '100%', minWidth: 0 }}>
                  <label htmlFor="password" style={{ display: 'block', marginBottom: 4, fontSize: '0.875rem' }}>
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="add-user-input"
                  />
                </div>
              </div>
              <div className="MuiBox-root jss156" style={{ marginTop: 24 }}>
                <button
                  type="submit"
                  className="MuiButtonBase-root MuiButton-root MuiButton-contained MuiButton-containedPrimary MuiButton-containedSizeLarge MuiButton-sizeLarge MuiButton-disableElevation"
                  disabled={submitting}
                  style={{
                    padding: '8px 22px',
                    backgroundColor: '#D10B0B',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 4,
                    cursor: submitting ? 'not-allowed' : 'pointer',
                    fontSize: '1rem',
                  }}
                >
                  {submitting ? 'Adding...' : 'Add User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
