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
    const goBack = () => setStepNumber(prev => Math.max(0, prev - 1));

    const steps: ISteps[] = [
        {
            name: "sequences & run",
            component: <DatabaseSetupComponent advanceStep={advanceStep} update={setDatasetSetupInput} initial={databaseSetupInput} />,
        },
        {
            name: "alerts",
            component: <AlertNotifSetupComponent advanceStep={advanceStep} update={setAlertNotifSetupInput} initial={alertNotifSetupInput} goBack={goBack} />,
        },
        {
            name: "review",
            component: <SummaryComponent databaseSetupInput={databaseSetupInput} alertNotifSetupInput={alertNotifSetupInput} goBack={goBack} />
        }
    ]

    return (
        <div className="nano-wizard">
            <h3>New project</h3>
            <p className="nano-wizard-sub">Tell nanoCAS what to watch and what to alert on. Three short steps.</p>
            <div className="module-stepbar">
                <ul className="steps">
                    {steps.map((s, i) => (
                        <li key={i} className={stepNumber === i ? 'active' : (stepNumber > i ? 'done' : '')}>
                            <span className="step-no">{i + 1}</span>{s.name}
                        </li>
                    ))}
                </ul>
            </div>
            {steps[stepNumber].component}
        </div>
    );
}

export default SetupComponent;
