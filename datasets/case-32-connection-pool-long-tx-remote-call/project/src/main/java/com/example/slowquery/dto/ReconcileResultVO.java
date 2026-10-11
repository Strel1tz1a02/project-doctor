package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ReconcileResultVO {
    private int batchSize;
    private int processed;

    public ReconcileResultVO(int batchSize, int processed) {
        this.batchSize = batchSize;
        this.processed = processed;
    }
}
