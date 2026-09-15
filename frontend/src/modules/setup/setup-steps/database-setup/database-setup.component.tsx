import React, { FunctionComponent, useState } from 'react';
import AlertDataSetup from "./alert-data-setup/alert-data-setup.component";
import { ILocationConfig } from "./database-setup.interfaces";
import { IAlertData } from "./alert-data-setup/alert-data-setup.interfaces";
import { IDatabaseSetupProps } from '../../setup.interfaces';
import LocationsSetupComponent from "./locations-setup/locations-setup.component";
import DeviceConfigurationComponent from "./device-configuration/device-configuration.component";
import { IDeviceConfig } from "./device-configuration/device-configuration.interfaces";

const DatabaseSetupComponent: FunctionComponent<IDatabaseSetupProps> = ({ advanceStep, update, initial }) => {
    const [alertData, setAlertData] = useState<IAlertData>({ queries: initial.queries, gff_file: initial.gff_file });
    const [locationConfig, setLocationConfig] = useState<ILocationConfig>(initial.locations);
    const [deviceConfig, setDeviceConfig] = useState<IDeviceConfig>(initial.device);
    const [error, setError] = useState<string>("");

    const updateDatabaseSetupConfiguration = () => {
        setError("");
        if (!locationConfig.nanoporeLocation.trim()) {
            setError("The nanopore output directory is required.");
            return;
        }
        if (alertData.queries.length === 0) {
            setError("Add at least one alert sequence (upload a FASTA and pick the sequences to monitor).");
            return;
        }
        const invalidQueries = alertData.queries.filter(q =>
            (q.alert_on_depth && (!q.depth_threshold || isNaN(parseFloat(q.depth_threshold)))) ||
            (q.alert_on_breadth && (!q.breadth_threshold || isNaN(parseFloat(q.breadth_threshold))))
        );
        if (invalidQueries.length > 0) {
            setError("Every enabled alert needs a numeric threshold.");
            return;
        }
        update({
            queries: alertData.queries,
            gff_file: alertData.gff_file,
            locations: locationConfig,
            device: deviceConfig
        });
        advanceStep();
    };

    return (
        <div className="container-fluid vspacer-100 d-flex p-0 flex-column h-100">
            <div className="vspacer-50" />
            <div className="twline"><span>NANOPORE SETUP</span></div>
            <div className="row justify-content-around">
                <LocationsSetupComponent initialConfig={locationConfig} updateConfig={setLocationConfig} />
                <DeviceConfigurationComponent initialConfig={deviceConfig} updateConfig={setDeviceConfig} />
            </div>
            <div className="vspacer-50" />
            <div className="twline"><span>ALERT SEQUENCES</span></div>
            <AlertDataSetup initialConfig={alertData} updateConfig={setAlertData} />
            <br />
            <div className="vspacer-50" />
            <hr />
            <br />
            {error && <div className="mx-auto col-sm-8 alert alert-danger text-left">{error}</div>}
            <div className="container text-center">
                <button className="btn btn-success col-lg-2 mx-auto" onClick={updateDatabaseSetupConfiguration}>
                    Next Step
                </button>
            </div>
        </div>
    );
};

export default DatabaseSetupComponent;
