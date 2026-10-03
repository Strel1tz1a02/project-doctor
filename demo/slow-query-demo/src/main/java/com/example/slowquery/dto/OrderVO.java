package com.example.slowquery.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class OrderVO {
    private Long orderId;
    private String orderNo;
    private BigDecimal amount;
    private String status;
    private LocalDateTime createdAt;
    private String userEmail;
    private String userName;
}
