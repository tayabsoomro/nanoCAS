import React from "react";
import {IDatabseSetupInput} from './setup-steps/database-setup/database-setup.interfaces';
import {IAlertNotifSetupInput} from './setup-steps/alert-notif-setup/alert-notif-setup.interfaces'
import {IDeviceConfig} from "./setup-steps/database-setup/device-configuration/device-configuration.interfaces";

type IDeviceConfigSetupProps = {
    advanceStep: () => void,
    update: React.Dispatch<React.SetStateAction<IDeviceConfig>>,
}

type IDatabaseSetupProps = {
    advanceStep: () => void,
    update: React.Dispatch<React.SetStateAction<IDatabseSetupInput>>,
    initial: IDatabseSetupInput,
}

type IAlertNotifSetupProps = {
    advanceStep: () => void,
    update: React.Dispatch<React.SetStateAction<IAlertNotifSetupInput>>,
    initial: IAlertNotifSetupInput,
}

type ISteps = {
    name: string,
    component: React.ReactElement,
}

export type {
    IDatabaseSetupProps,
    IDeviceConfigSetupProps,
    IAlertNotifSetupProps,
    ISteps
}
