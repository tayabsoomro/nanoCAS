import React, {FunctionComponent, useEffect, useState} from 'react';
import {IDatabaseSetupConstituent, ILocationConfig} from "../database-setup.interfaces";
import { OverlayTrigger, Tooltip } from 'react-bootstrap';
import axios from 'axios';

const API_ENDPOINT = process.env.REACT_APP_API_ENDPOINT ?? '';

type IKeys = "nanoporeLocation"
const initial_location_config: ILocationConfig = {
    nanoporeLocation: ""
}

const LocationsSetupComponent: FunctionComponent<IDatabaseSetupConstituent<ILocationConfig>> = ({updateConfig}) => {
    const [locationConfig, setLocationConfig] = useState(initial_location_config);
    const [error, setError] = useState("");
    const [defaultPath, setDefaultPath] = useState("");
    const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
    const [uploadStatus, setUploadStatus] = useState("");
    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        axios.get(`${API_ENDPOINT}/get_default_nanopore_path`)
            .then(res => {
                const path = res.data.path;
                setDefaultPath(path);
                setLocationConfig(prev => {
                    if (!prev.nanoporeLocation) {
                        return { ...prev, nanoporeLocation: path };
                    }
                    return prev;
                });
            })
            .catch(err => console.error("Could not fetch default nanopore path", err));
    }, []);

    const handleDataChange = (key: IKeys) => (evt: React.ChangeEvent<HTMLInputElement>) => {
        const value = evt.target.value;
        setLocationConfig((prev) => ({...prev, [key]: value}));
        setError(value ? "" : "Nanopore directory is required.");
    };

    useEffect(() => {
        updateConfig((prevState: any) => ({
            ...prevState,
            nanoporeLocation: locationConfig.nanoporeLocation
        }));
    }, [locationConfig, updateConfig]);

    const handleFastqUpload = async (evt: React.ChangeEvent<HTMLInputElement>) => {
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
            const res = await axios.post(`${API_ENDPOINT}/upload_fastq`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            setUploadedFiles(prev => [...prev, ...res.data.uploaded]);
            setUploadStatus(`Successfully uploaded ${res.data.uploaded.length} file(s).`);
        } catch (err: any) {
            const msg = err?.response?.data?.error || "Upload failed. Ensure files are .fastq, .fastq.gz, .fq, or .fq.gz";
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
            <h4>Nanopore Location</h4>
            <p>
                Enter the server-side directory where Nanopore FASTQ data is (or will be) stored.
                When running locally alongside a sequencer, paste the sequencer output path.
                In a cloud or browser environment, use the default path and upload FASTQ files below.
            </p>
            <div className="vspacer-10"/>
            <div className="row ml-auto align-items-center">
                <div className="col pr-1">
                    <OverlayTrigger
                        placement="top"
                        overlay={<Tooltip id="tooltip">Server-side path to the directory where FASTQ files are stored</Tooltip>}
                    >
                        <input
                            name="nanoporeLocationText"
                            className={`form-control ${error ? 'is-invalid' : ''}`}
                            placeholder="/path/to/minion/dropbox"
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
                    <strong>Upload FASTQ Files</strong>
                    <span className="text-muted small ml-2">(optional — for cloud/browser environments)</span>
                </div>
                <div className="card-body">
                    <p className="text-muted small mb-2">
                        Upload <code>.fastq</code>, <code>.fastq.gz</code>, <code>.fq</code>, or <code>.fq.gz</code> files
                        directly to the directory above. When running alongside a live sequencer, this step is not needed — the sequencer will populate the directory automatically.
                    </p>
                    <input
                        type="file"
                        className="form-control-file"
                        accept=".fastq,.fastq.gz,.fq,.fq.gz"
                        multiple
                        disabled={uploading || !locationConfig.nanoporeLocation}
                        onChange={handleFastqUpload}
                    />
                    {uploading && (
                        <div className="mt-2 text-primary small">Uploading...</div>
                    )}
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
