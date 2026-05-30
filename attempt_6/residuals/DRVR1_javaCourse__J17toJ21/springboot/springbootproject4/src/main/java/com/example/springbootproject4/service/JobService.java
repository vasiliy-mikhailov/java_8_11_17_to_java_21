package com.example.springbootproject4.service;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.example.springbootproject4.model.Job;
import com.example.springbootproject4.repo.JobRepo;

@Service
public class JobService {
    @Autowired
    JobRepo jobRepo;

    public List<Job> getAllJobs() {
        return jobRepo.getAllJobs();
    }

    public Job getJobById(long id) {
        return jobRepo.getJobById(id);
    }

    public Job createJob(Job job) {
        return jobRepo.createJob(job);
    }

    public Job updateJob(Job job) {
        return jobRepo.updateJob(job);
    }

    public boolean deleteJob(Job job) {
        return jobRepo.deleteJob(job);
    }
}
