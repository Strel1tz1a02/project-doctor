package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ProductVO {
    private long productId;
    private String name;
    private String categoryName;
    private String brandName;
}
