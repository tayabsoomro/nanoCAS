import React, { FunctionComponent, useState } from 'react';
import AlertDataSetup from "./alert-data-setup/alert-data-setup.component";
import { ILocationConfig } from "./database-setup.interfaces";
import { IAlertData } from "./alert-data-setup/alert-data-setup.interfaces";
import { IDatabaseSetupProps } from '../../setup.interfaces';
import LocationsSetupComponent from "./locations-setup/locations-setup.component";
import DeviceConfigurationComponent from "./device-configuration/device-configuration.component";
import { IDeviceConfig } from "./device-configuration/device-configuration.interfaces";

const DatabaseSetupComponent: FunctionComponent<IDatabaseSetupProps> = ({ advanceStep, update, initial }) => {
    const [alertData, setAlertData] = useState<IAlertData>({ queries: initial.queries, gff_file: initial.gff_file, regions: initial.regions, classifier: initial.classifier });
    const [locationConfig, setLocationConfig] = useState<ILocationConfig>(initial.locations);
    const [deviceConfig, setDeviceConfig] = useState<IDeviceConfig>(initial.device);
    const [error, setError] = useState<string>("");

    const next = () => {
        setError("");
        if (!locationConfig.nanoporeLocation.trim()) {
            setError("Enter the directory the sequencer writes reads to.");
            return;
        }
        if (alertData.queries.length === 0) {
            setError("Add at least one sequence to watch for.");
            return;
        }
        const invalid = alertData.queries.filter(q =>
            (q.alert_on_depth && (!q.depth_threshold || isNaN(parseFloat(q.depth_threshold)))) ||
            (q.alert_on_breadth && (!q.breadth_threshold || isNaN(parseFloat(q.breadth_threshold)))) ||
            (q.alert_on_reads && (!q.reads_threshold || isNaN(parseFloat(q.reads_threshold)))) ||
            (q.alert_on_fraction && (!q.fraction_threshold || isNaN(parseFloat(q.fraction_threshold))))
        );
        if (invalid.length > 0) {
            setError("Every enabled alert needs a numeric threshold.");
            return;
        }
        if (alertData.classifier && alertData.classifier.name !== 'minimap2' && !alertData.classifier.database) {
            setError("Enter the database path for the selected classifier.");
            return;
        }
        update({ queries: alertData.queries, gff_file: alertData.gff_file, regions: alertData.regions,
                 classifier: alertData.classifier, locations: locationConfig, device: deviceConfig });
        advanceStep();
    };

    return (
        <div>
            <div className="nano-wizard-panel">
                <LocationsSetupComponent initialConfig={locationConfig} updateConfig={setLocationConfig} />
                <DeviceConfigurationComponent initialConfig={deviceConfig} updateConfig={setDeviceConfig} />
            </div>
            <div className="nano-wizard-panel">
                <AlertDataSetup initialConfig={alertData} updateConfig={setAlertData} />
            </div>
            {error && <div className="nano-alert-banner critical"><span className="nano-alert-message">{error}</span></div>}
            <div className="nano-wizard-actions">
                <span className="spacer" />
                <button className="btn btn-primary" onClick={next}>Continue</button>
            </div>
        </div>
    );
};

export default DatabaseSetupComponent;
