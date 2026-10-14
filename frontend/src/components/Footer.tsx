import React from 'react';
import '../styles/footer.css';

const Footer: React.FC = () => {
  return (
    <footer className="nano-footer">
      <div className="nano-footer-container">
        <div className="nano-footer-content">
          <div className="nano-footer-info">
            <p>nanoCAS · Nanopore Classification &amp; Alerting System</p>
            <p>© {new Date().getFullYear()} Coadunate</p>
            <p><a href="https://github.com/tayabsoomro/nanoCAS">Source &amp; documentation</a></p>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
