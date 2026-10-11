package com.example.slowquery.service;

import com.example.slowquery.dto.ProviderReleaseVO;
import com.example.slowquery.mapper.ProviderReleaseMapper;
import com.example.slowquery.model.ProviderRelease;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class ProviderReleaseService {

    private final ProviderReleaseMapper providerReleaseMapper;

    public ProviderReleaseService(ProviderReleaseMapper providerReleaseMapper) {
        this.providerReleaseMapper = providerReleaseMapper;
    }

    public List<ProviderReleaseVO> recentByProvider(String provider, int size) {
        List<ProviderRelease> releases = providerReleaseMapper.findRecentByProvider(provider, size);
        List<ProviderReleaseVO> result = new ArrayList<>();

        for (ProviderRelease release : releases) {
            ProviderReleaseVO vo = new ProviderReleaseVO();
            vo.setReleaseId(release.getId());
            vo.setProvider(release.getProvider());
            vo.setReleaseTag(release.getReleaseTag());
            vo.setCreatedAt(release.getCreatedAt());
            result.add(vo);
        }

        return result;
    }

    public List<ProviderRelease> listAll() {
        return providerReleaseMapper.findAllReleases();
    }
}
