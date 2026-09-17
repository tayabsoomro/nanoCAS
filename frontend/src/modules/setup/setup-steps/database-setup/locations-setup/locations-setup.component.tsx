import React, {FunctionComponent, useEffect, useState} from 'react';
import {IDatabaseSetupConstituent, ILocationConfig} from "../database-setup.interfaces";
import { api } from '../../../../../api';

const LocationsSetupComponent: FunctionComponent<IDatabaseSetupConstituent<ILocationConfig>> = ({initialConfig, updateConfig}) => {
    const [locationConfig, setLocationConfig] = useState<ILocationConfig>(initialConfig);
    const [defaultPath, setDefaultPath] = useState("");

    useEffect(() => {
        api.get('/get_default_nanopore_path')
            .then(res => {
                const path = res.data.path;
                setDefaultPath(path);
                setLocationConfig(prev => prev.nanoporeLocation ? prev : { ...prev, nanoporeLocation: path });
            })
            .catch(() => { });
    }, []);

    useEffect(() => {
        updateConfig(locationConfig);
    }, [locationConfig, updateConfig]);

    const set = (key: keyof ILocationConfig) => (evt: React.ChangeEvent<HTMLInputElement>) => {
        const value = evt.target.value;
        setLocationConfig((prev) => ({...prev, [key]: value}));
    };

    return (
        <div>
            <h4>Run</h4>
            <p>Where the sequencer writes reads. nanoCAS watches this folder and finds the run's sequencing summary next to it.</p>
            <div className="nano-field-row">
                <label htmlFor="projectName">Project name</label>
                <div>
                    <input id="projectName" className="form-control" placeholder="e.g. Field sample 12" type="text" maxLength={80}
                           value={locationConfig.projectName} onChange={set("projectName")} />
                </div>
            </div>
            <div className="nano-field-row">
                <label htmlFor="nanoporeLocation">Reads directory</label>
                <div>
                    <input id="nanoporeLocation" className="form-control" type="text"
                           placeholder="/Library/MinKNOW/data/<experiment>/<sample>/<run>/fastq_pass"
                           value={locationConfig.nanoporeLocation} onChange={set("nanoporeLocation")} />
                    <div className="form-text">
                        Usually the run's <code>fastq_pass</code> folder. Created if it does not exist yet.
                        {defaultPath && locationConfig.nanoporeLocation !== defaultPath && (
                            <> <button type="button" className="btn btn-link btn-sm p-0 align-baseline"
                                       onClick={() => setLocationConfig(prev => ({ ...prev, nanoporeLocation: defaultPath }))}>
                                Use the default folder
                            </button></>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default LocationsSetupComponent;
