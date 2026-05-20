import React from 'react';
import { BrowserRouter as Router, Route, Switch } from 'react-router-dom';
import Header from './components/Header';
import Footer from './components/Footer';
import ProjectList from './modules/project/ProjectList';
import ProjectDetail from './modules/project/ProjectDetail';
import SetupComponent from './modules/setup/setup.component';
import './styles/theme.css';
import './app.component.css';

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

export const io = require('socket.io-client');
const socketUrl = API_ENDPOINT || window.location.origin;
// Let socket.io auto-negotiate. The default ['polling', 'websocket']
// starts on long-polling then upgrades to ws if the proxy supports it.
// Forcing 'polling' (the previous setting) was a workaround for a
// hosting environment that doesn't allow ws, but it cost us 25-second
// long-poll hangs in the server log — see LOGBOOK §4.6. If a future
// deployment really can't do websockets, set REACT_APP_SOCKET_TRANSPORTS
// to 'polling' to pin it.
const transports = process.env.REACT_APP_SOCKET_TRANSPORTS
    ? process.env.REACT_APP_SOCKET_TRANSPORTS.split(',').map(s => s.trim())
    : undefined;
export const socket = io.connect(socketUrl, transports ? { transports } : {});

socket.on('connect', function() {
    socket.send('message', 'User has connected!');
});

socket.on('connect_error', (err: any) => {
    console.log(`connect error due to ${err}`)
})

const AppComponent = () => {
    return (
        <Router>
            <div className="nano-app">
                <Header />
                <main className="nano-main">
                    <Switch>
                        <Route exact path="/" component={ProjectList} />
                        <Route path="/setup" component={SetupComponent} />
                        <Route path="/project/:id/:tab?" component={ProjectDetail} />
                    </Switch>
                </main>
                <Footer />
            </div>
        </Router>
    );
}

export default AppComponent;
