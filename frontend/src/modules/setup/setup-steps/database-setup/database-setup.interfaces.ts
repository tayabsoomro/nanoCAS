import {IQuery, IClassifierSelection} from "./alert-data-setup/alert-data-setup.interfaces"
import { GffFeature } from "../../../../api";
import {IDeviceConfig} from "./device-configuration/device-configuration.interfaces"
import React from "react";

type ILocationConfig = {
    nanoporeLocation: string,
    projectName: string,
}

type IDatabseSetupInput = {
    queries: IQuery[],
    gff_file?: string,
    regions?: GffFeature[],
    classifier?: IClassifierSelection,
    locations: ILocationConfig,
    device: IDeviceConfig,
}

type IDatabaseSetupConstituent<T> = {
    initialConfig: T,
    updateConfig: React.Dispatch<React.SetStateAction<T>>
}

export type {
    IDatabaseSetupConstituent,
    IDatabseSetupInput,
    ILocationConfig
}
