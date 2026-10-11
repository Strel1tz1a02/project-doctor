package com.example.slowquery.model;

import lombok.Data;

@Data
public class Order {
    private Long id;
    private Long userId;
    private String status;
    private Long amount;
    private Long createdAtMs;
}
