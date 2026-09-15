type IAlertData = {
    queries: IQuery[],
    gff_file?: string
}

type IQuery = {
    name: string,
    file: string,
    alert_on_depth: boolean,
    depth_threshold?: string,
    alert_on_breadth: boolean,
    breadth_threshold?: string,
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
    IFastaRecord
}
