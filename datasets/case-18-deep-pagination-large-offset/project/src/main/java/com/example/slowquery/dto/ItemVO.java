package com.example.slowquery.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class ItemVO {
    private Long itemId;
    private String name;
    private String category;
    private BigDecimal price;
    private LocalDateTime createdAt;
}
