import React, {FunctionComponent, useEffect, useState} from "react";
import {IDatabaseSetupConstituent} from "../database-setup.interfaces";
import { IDeviceConfig } from "./device-configuration.interfaces";
import { api } from "../../../../../api";

/**
 * Optional MinKNOW position picker. When a position is selected, alerts
 * are also posted into the MinKNOW UI of that instrument and the
 * run-health monitor reads its live acquisition state.
 */
const DeviceConfigurationComponent: FunctionComponent<IDatabaseSetupConstituent<IDeviceConfig>> = ({initialConfig, updateConfig}) => {
    const [devices, setDevices] = useState<string[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [failed, setFailed] = useState(false);
    const [selectedDevice, setSelectedDevice] = useState(initialConfig.device || "");

    useEffect(() => {
        let cancelled = false;
        api.get('/index_devices')
            .then(res => { if (!cancelled) setDevices(Array.isArray(res.data) ? res.data : []); })
            .catch(() => { if (!cancelled) setFailed(true); })
            .finally(() => { if (!cancelled) setLoaded(true); });
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        updateConfig({ device: selectedDevice });
    }, [selectedDevice, updateConfig]);

    return (
        <div className="col-lg-4 m-0 container">
            <br/>
            <h4>MinKNOW device (optional)</h4>
            <p className="text-muted small">
                If MinKNOW runs on this machine, pick the flow-cell position to receive alerts inside MinKNOW and
                to let nanoCAS read the live acquisition state.
            </p>
            {!loaded ? (
                <div className="text-muted small"><i className="fa fa-spinner fa-spin"/> Searching for devices…</div>
            ) : (
                <>
                    <select
                        className="form-control"
                        onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setSelectedDevice(e.target.value)}
                        value={selectedDevice}
                    >
                        <option value="">Run without a device</option>
                        {devices.map((device: string) => (
                            <option key={device} value={device}>{device}</option>
                        ))}
                    </select>
                    {failed && <div className="text-muted small mt-1">Could not query MinKNOW.</div>}
                    {!failed && devices.length === 0 && <div className="text-muted small mt-1">No MinKNOW positions found (MinKNOW not running or not reachable on localhost).</div>}
                </>
            )}
            <br/>
        </div>
    );
};

export default DeviceConfigurationComponent;
