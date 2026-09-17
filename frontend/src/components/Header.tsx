import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api';
import '../styles/header.css';

import logo from '../assets/nanoCAS_icon.png';

type BackendState = 'ok' | 'degraded' | 'down' | 'unknown';

const Header: React.FC = () => {
  const location = useLocation();
  const [backend, setBackend] = useState<BackendState>('unknown');
  const [tools, setTools] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await api.get('/health');
        if (cancelled) return;
        setBackend(res.data.status === 'ok' ? 'ok' : 'degraded');
        const missing = Object.entries(res.data.tools || {}).filter(([, v]) => !v).map(([k]) => k);
        setTools(missing.length ? `missing: ${missing.join(', ')}` : `v${res.data.version}`);
      } catch {
        if (!cancelled) { setBackend('down'); setTools('backend unreachable'); }
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const isActive = (path: string) => (path === '/' ? location.pathname === '/' : location.pathname.startsWith(path));

  return (
    <header className="nano-header">
      <div className="nano-header-container">
        <div className="nano-logo-container">
          <Link to="/">
            <img src={logo} alt="" className="nano-logo" />
            <span className="nano-wordmark">nanoCAS<small>Nanopore Classification &amp; Alerting System</small></span>
          </Link>
        </div>
        <nav className="nano-nav">
          <ul className="nano-nav-list">
            <li className="nano-nav-item">
              <Link to="/" className={`nano-nav-link ${isActive('/') ? 'nano-nav-active' : ''}`}>Projects</Link>
            </li>
            <li className="nano-nav-item">
              <Link to="/setup" className={`nano-nav-link ${isActive('/setup') ? 'nano-nav-active' : ''}`}>New project</Link>
            </li>
            <li className="nano-nav-item">
              <Link to="/summary" className={`nano-nav-link ${isActive('/summary') ? 'nano-nav-active' : ''}`}>Across runs</Link>
            </li>
            <li className="nano-nav-item">
              <span className={`nano-backend-status ${backend}`} title={tools}>
                <span className="nano-status-dot" />
                {backend === 'ok' ? 'backend online' : backend === 'degraded' ? 'tools missing' : backend === 'down' ? 'backend offline' : '…'}
              </span>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
};

export default Header;
