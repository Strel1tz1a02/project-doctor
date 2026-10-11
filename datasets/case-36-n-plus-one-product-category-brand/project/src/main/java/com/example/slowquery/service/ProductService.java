package com.example.slowquery.service;

import com.example.slowquery.dto.ProductVO;
import com.example.slowquery.mapper.ProductMapper;
import com.example.slowquery.model.Product;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class ProductService {

    private final ProductMapper productMapper;

    public ProductService(ProductMapper productMapper) {
        this.productMapper = productMapper;
    }

    public List<ProductVO> buildProducts(int size) {
        List<Product> products = productMapper.findRecentProducts(size);
        List<ProductVO> result = new ArrayList<>();
        for (Product product : products) {
            ProductVO vo = new ProductVO();
            vo.setProductId(product.getId());
            vo.setName(product.getName());
            vo.setCategoryName(productMapper.findCategoryNameById(product.getCategoryId()));
            result.add(vo);
        }
        for (int i = 0; i < products.size(); i++) {
            result.get(i).setBrandName(productMapper.findBrandNameById(products.get(i).getBrandId()));
        }
        return result;
    }
}
