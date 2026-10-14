import React, {FunctionComponent, useEffect, useState} from "react";
import {IDatabaseSetupConstituent} from "../database-setup.interfaces";
import { IDeviceConfig } from "./device-configuration.interfaces";
import { api } from "../../../../../api";

/** Optional MinKNOW position: alerts are also posted into MinKNOW and the
 *  live acquisition state feeds the run-health rules. */
const DeviceConfigurationComponent: FunctionComponent<IDatabaseSetupConstituent<IDeviceConfig>> = ({initialConfig, updateConfig}) => {
    const [devices, setDevices] = useState<string[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [selectedDevice, setSelectedDevice] = useState(initialConfig.device || "");

    useEffect(() => {
        let cancelled = false;
        api.get('/index_devices')
            .then(res => { if (!cancelled) setDevices(Array.isArray(res.data) ? res.data : []); })
            .catch(() => { })
            .finally(() => { if (!cancelled) setLoaded(true); });
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        updateConfig({ device: selectedDevice });
    }, [selectedDevice, updateConfig]);

    return (
        <div className="nano-field-row">
            <label htmlFor="device">MinKNOW position</label>
            <div>
                <select id="device" className="form-select" value={selectedDevice}
                        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setSelectedDevice(e.target.value)}>
                    <option value="">None (optional)</option>
                    {devices.map((device: string) => <option key={device} value={device}>{device}</option>)}
                </select>
                <div className="form-text">
                    {!loaded ? 'Looking for MinKNOW…'
                        : devices.length === 0 ? 'No MinKNOW found on this machine. Alerts still show in nanoCAS and by e-mail/SMS.'
                        : 'Alerts are also shown inside MinKNOW and its live status feeds the run-health rules.'}
                </div>
            </div>
        </div>
    );
};

export default DeviceConfigurationComponent;
