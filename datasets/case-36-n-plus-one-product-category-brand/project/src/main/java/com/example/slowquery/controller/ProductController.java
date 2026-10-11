package com.example.slowquery.controller;

import com.example.slowquery.dto.ProductVO;
import com.example.slowquery.service.ProductService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/products")
public class ProductController {

    private final ProductService productService;

    public ProductController(ProductService productService) {
        this.productService = productService;
    }

    @GetMapping("/recent")
    public List<ProductVO> recent(@RequestParam(defaultValue = "100") int size) {
        return productService.buildProducts(size);
    }
}
