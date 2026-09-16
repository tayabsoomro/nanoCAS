import { GffFeature } from "../../../../../api";

type IClassifierSelection = {
    name: string,
    database?: string,
}

type IAlertData = {
    queries: IQuery[],
    gff_file?: string,
    regions?: GffFeature[],
    classifier?: IClassifierSelection,
}

type IQuery = {
    name: string,
    file: string,
    alert_on_depth: boolean,
    depth_threshold?: string,
    alert_on_breadth: boolean,
    breadth_threshold?: string,
    alert_on_reads?: boolean,
    reads_threshold?: string,
    alert_on_fraction?: boolean,
    fraction_threshold?: string,
    header?: string,
    headers?: string[],
    description?: string,
    length?: number,
}

type IFastaRecord = {
    id: string,
    description: string,
    length: number,
}

export type {
    IAlertData,
    IQuery,
    IFastaRecord,
    IClassifierSelection
}
