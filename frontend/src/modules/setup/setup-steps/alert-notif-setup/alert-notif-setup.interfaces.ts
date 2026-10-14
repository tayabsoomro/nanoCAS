import { RunHealthConfig } from "../../../../api";

type IEmailConfig = {
    sender: string,
    recipient: string,
    smtpServer: string,
    smtpPort: number,
    password: string,
}

type IAlertNotifSetupInput = {
    enableEmail: boolean,
    emailConfig?: IEmailConfig,
    enableSMS: boolean,
    smsRecipient?: string,
    runHealthConfig?: Partial<RunHealthConfig>,
}

export type {
    IAlertNotifSetupInput,
    IEmailConfig
}
