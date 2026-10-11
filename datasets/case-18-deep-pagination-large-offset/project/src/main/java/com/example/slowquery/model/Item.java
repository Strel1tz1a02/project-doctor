package com.example.slowquery.model;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class Item {
    private Long id;
    private String name;
    private String category;
    private BigDecimal price;
    private LocalDateTime createdAt;
}
