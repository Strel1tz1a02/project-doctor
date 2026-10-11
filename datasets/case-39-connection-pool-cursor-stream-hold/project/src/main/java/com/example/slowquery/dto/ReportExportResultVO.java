package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ReportExportResultVO {
    private int limit;
    private int exported;
    private int outputLength;

    public ReportExportResultVO(int limit, int exported, int outputLength) {
        this.limit = limit;
        this.exported = exported;
        this.outputLength = outputLength;
    }
}
