package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ExportStreamSummaryVO {
    private int exported;
    private long bytesWritten;

    public ExportStreamSummaryVO(int exported, long bytesWritten) {
        this.exported = exported;
        this.bytesWritten = bytesWritten;
    }
}
