package com.example.slowquery.model;

import lombok.Data;

@Data
public class ReconcileTask {
    private long id;
    private String orderNo;
    private long amount;
    private String status;
    private String gatewayRef;
    private long createdAtMs;
}
