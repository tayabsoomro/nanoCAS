import React from 'react';
import ReactDOM from 'react-dom';
// Bootstrap is bundled (not loaded from a CDN) so the UI works on an
// instrument laptop with no internet access.
import 'bootstrap/dist/css/bootstrap.min.css';
import AppComponent from './app.component';

ReactDOM.render(
    <React.StrictMode>
        <AppComponent/>
    </React.StrictMode>,
    document.getElementById('root')
);

