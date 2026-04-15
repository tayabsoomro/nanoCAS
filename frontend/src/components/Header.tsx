import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import '../styles/header.css';

import logo from '../assets/nanoCAS_icon.png';

const Header: React.FC = () => {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <header className="nano-header">
      <div className="nano-header-container">
        <div className="nano-logo-container">
          <Link to="/">
            <img
              src={logo}
              alt="nanoCAS"
              className="nano-logo"
            />
          </Link>
        </div>
        <nav className="nano-nav">
          <ul className="nano-nav-list">
            <li className="nano-nav-item">
              <Link to="/" className={`nano-nav-link ${isActive('/') ? 'nano-nav-active' : ''}`}>Projects</Link>
            </li>
            <li className="nano-nav-item">
              <Link to="/setup" className={`nano-nav-link ${isActive('/setup') ? 'nano-nav-active' : ''}`}>New Project</Link>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
};

export default Header;
