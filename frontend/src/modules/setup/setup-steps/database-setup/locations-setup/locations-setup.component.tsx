import React, {FunctionComponent, useEffect, useState} from 'react';
import {IDatabaseSetupConstituent, ILocationConfig} from "../database-setup.interfaces";
import { OverlayTrigger, Tooltip } from 'react-bootstrap';
import { api } from '../../../../../api';

const LocationsSetupComponent: FunctionComponent<IDatabaseSetupConstituent<ILocationConfig>> = ({initialConfig, updateConfig}) => {
    const [locationConfig, setLocationConfig] = useState<ILocationConfig>(initialConfig);
    const [error, setError] = useState("");
    const [defaultPath, setDefaultPath] = useState("");
    const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
    const [uploadStatus, setUploadStatus] = useState("");
    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        api.get('/get_default_nanopore_path')
            .then(res => {
                const path = res.data.path;
                setDefaultPath(path);
                setLocationConfig(prev => prev.nanoporeLocation ? prev : { ...prev, nanoporeLocation: path });
            })
            .catch(err => console.error("Could not fetch default nanopore path", err));
    }, []);

    useEffect(() => {
        updateConfig(locationConfig);
    }, [locationConfig, updateConfig]);

    const handleDataChange = (key: keyof ILocationConfig) => (evt: React.ChangeEvent<HTMLInputElement>) => {
        const value = evt.target.value;
        setLocationConfig((prev) => ({...prev, [key]: value}));
        if (key === 'nanoporeLocation') setError(value ? "" : "Nanopore directory is required.");
    };

    const handleFastaUpload = async (evt: React.ChangeEvent<HTMLInputElement>) => {
        const files = evt.target.files;
        if (!files || files.length === 0) return;
        setUploading(true);
        setUploadStatus("");
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }
        formData.append('target_dir', locationConfig.nanoporeLocation);
        try {
            const res = await api.post('/upload_reference', formData);
            setUploadedFiles(prev => [...prev, ...res.data.uploaded]);
            setUploadStatus(`Successfully uploaded ${res.data.uploaded.length} file(s).`);
        } catch (err: any) {
            const msg = err?.response?.data?.error || "Upload failed. Ensure files are .fasta, .fa, .fna, .fasta.gz, .fa.gz, or .fna.gz";
            setUploadStatus(msg);
        } finally {
            setUploading(false);
            evt.target.value = "";
        }
    };

    const useDefaultPath = () => {
        setLocationConfig(prev => ({ ...prev, nanoporeLocation: defaultPath }));
        setError("");
    };

    return (
        <div className="col-lg-7 m-0 container">
            <br/>
            <h4>Project</h4>
            <div className="row align-items-center">
                <div className="col">
                    <input
                        name="projectName"
                        className="form-control"
                        placeholder="Project name (optional), e.g. Field sample 12 / FluA screen"
                        type="text"
                        maxLength={80}
                        value={locationConfig.projectName}
                        onChange={handleDataChange("projectName")}
                    />
                </div>
            </div>
            <div className="vspacer-20"/>
            <h4>Nanopore output directory</h4>
            <p>
                The server-side directory where MinKNOW writes basecalled reads for this run (typically the
                <code> fastq_pass</code> folder of the run). nanoCAS watches it for new FASTQ files and looks for
                the run's <code>sequencing_summary</code> file in it and its parent. The directory is created if
                it does not exist yet, so the project can be prepared before the run starts.
            </p>
            <div className="vspacer-10"/>
            <div className="row ml-auto align-items-center">
                <div className="col pr-1">
                    <OverlayTrigger
                        placement="top"
                        overlay={<Tooltip id="tooltip">Server-side path to the directory where Nanopore data is stored</Tooltip>}
                    >
                        <input
                            name="nanoporeLocationText"
                            className={`form-control ${error ? 'is-invalid' : ''}`}
                            placeholder="/data/<experiment>/<sample>/<run>/fastq_pass"
                            type="text"
                            value={locationConfig.nanoporeLocation}
                            onChange={handleDataChange("nanoporeLocation")}
                        />
                    </OverlayTrigger>
                    {error && <div className="invalid-feedback">{error}</div>}
                </div>
                {defaultPath && locationConfig.nanoporeLocation !== defaultPath && (
                    <div className="col-auto pl-1">
                        <button
                            type="button"
                            className="btn btn-outline-secondary btn-sm"
                            onClick={useDefaultPath}
                            title="Reset to the default server-managed upload directory"
                        >
                            Use Default
                        </button>
                    </div>
                )}
            </div>

            <div className="vspacer-20"/>
            <div className="card border-secondary">
                <div className="card-header bg-light">
                    <strong>Upload reads for offline analysis (optional)</strong>
                </div>
                <div className="card-body">
                    <p className="text-muted small mb-2">
                        When nanoCAS is not running next to the sequencer you can upload files into the directory above
                        instead. Note that reads must be <code>.fastq</code> / <code>.fastq.gz</code> to be processed; FASTA
                        files uploaded here are only stored.
                    </p>
                    <input
                        type="file"
                        className="form-control-file"
                        accept=".fasta,.fa,.fna,.fasta.gz,.fa.gz,.fna.gz"
                        multiple
                        disabled={uploading || !locationConfig.nanoporeLocation}
                        onChange={handleFastaUpload}
                    />
                    {uploading && <div className="mt-2 text-primary small">Uploading...</div>}
                    {uploadStatus && (
                        <div className={`mt-2 small alert ${uploadStatus.startsWith("Successfully") ? "alert-success" : "alert-danger"} py-1 px-2`}>
                            {uploadStatus}
                        </div>
                    )}
                    {uploadedFiles.length > 0 && (
                        <div className="mt-2">
                            <small className="text-muted">Uploaded:</small>
                            <ul className="small mb-0">
                                {uploadedFiles.map((f, i) => <li key={i}>{f}</li>)}
                            </ul>
                        </div>
                    )}
                </div>
            </div>
            <br/>
        </div>
    );
};

export default LocationsSetupComponent;
