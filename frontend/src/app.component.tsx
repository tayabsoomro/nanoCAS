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
export const socket = io.connect(socketUrl, { transports: ['polling'] });

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
