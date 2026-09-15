import React, {useState} from "react";

import {ISteps} from "./setup.interfaces";
import DatabaseSetupComponent from "./setup-steps/database-setup/database-setup.component";
import AlertNotifSetupComponent from './setup-steps/alert-notif-setup/alert-notif-setup.component';
import SummaryComponent from "./setup-steps/summary/summary.component";
import "./setup.component.css";
import {
    IDatabseSetupInput
} from "./setup-steps/database-setup/database-setup.interfaces";
import {IAlertNotifSetupInput} from "./setup-steps/alert-notif-setup/alert-notif-setup.interfaces";

const initial_db_setup_input: IDatabseSetupInput = {
    queries  : [],
    locations: {nanoporeLocation: "", projectName: ""},
    device: {device: ""}
};

const initial_alert_notif_setup_input: IAlertNotifSetupInput = {
    enableEmail: false,
    enableSMS: false,
}

const SetupComponent = () => {
    const [stepNumber, setStepNumber] = useState(0);
    // Wizard state is owned here and handed back to each step as
    // `initial`, so going back a step no longer wipes what was entered.
    const [databaseSetupInput, setDatasetSetupInput] = useState(initial_db_setup_input);
    const [alertNotifSetupInput, setAlertNotifSetupInput] = useState(initial_alert_notif_setup_input);

    const advanceStep = () => {
        if (stepNumber < (steps.length - 1)) {
            setStepNumber((prev) => prev + 1)
        }
    }

    const steps: ISteps[] = [
        {
            name: "sequences & location",
            component: <DatabaseSetupComponent advanceStep={advanceStep} update={setDatasetSetupInput} initial={databaseSetupInput} />,
        },
        {
            name: "alerts & notifications",
            component: <AlertNotifSetupComponent advanceStep={advanceStep} update={setAlertNotifSetupInput} initial={alertNotifSetupInput} />,
        },
        {
            name: "summary",
            component: <SummaryComponent databaseSetupInput={databaseSetupInput} alertNotifSetupInput={alertNotifSetupInput} />
        }
    ]

    return (
        <div className="container-fluid d-flex flex-column">
            <div className="vspacer-50"/>
            <div className="container-fluid text-center">
                <h3>New nanoCAS project</h3>
                <p>Step {stepNumber + 1} of {steps.length}</p>
            </div>
            <div className="vspacer-20"/>
            <div className="module-stepbar d-flex">
                <ul className="steps six clearfix justify-content-center">
                    {steps.map((s, i) => (
                        <li key={i} className={stepNumber === i ? 'active' : (stepNumber > i ? 'done' : '')}>
                            <span className="step-no">{i + 1}</span>{s.name}
                        </li>
                    ))}
                </ul>
            </div>
            <div className="container p-0">
                {steps[stepNumber].component}
            </div>
            {stepNumber > 0 && (
                <button className="btn btn-outline-danger m-2 mx-auto w-20" onClick={() => setStepNumber((prev) => prev - 1)}>
                    Previous
                </button>
            )}
            <div className="vspacer-20"/>
        </div>
    );
}

export default SetupComponent;
